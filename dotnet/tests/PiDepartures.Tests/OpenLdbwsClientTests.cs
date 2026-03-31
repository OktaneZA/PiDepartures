using System.Net;
using System.Xml;
using Microsoft.Extensions.Logging;
using Moq;
using PiDepartures.Services;

namespace PiDepartures.Tests;

public class OpenLdbwsClientTests
{
    // ── BackoffDelay ────────────────────────────────────────────────────

    [Theory]
    [InlineData(1, 2.0)]
    [InlineData(2, 4.0)]
    [InlineData(3, 8.0)]
    public void BackoffDelay_CalculatesExponentialDelay(int failures, double expectedSeconds)
    {
        Assert.Equal(expectedSeconds, OpenLdbwsClient.BackoffDelay(failures));
    }

    [Fact]
    public void BackoffDelay_CapsAt120Seconds_For7Failures()
    {
        // 2 * 2^6 = 128, capped to 120
        Assert.Equal(120.0, OpenLdbwsClient.BackoffDelay(7));
    }

    [Fact]
    public void BackoffDelay_CapsAt120Seconds_For10Failures()
    {
        Assert.Equal(120.0, OpenLdbwsClient.BackoffDelay(10));
    }

    // ── SOAP XML Parsing (via FetchDeparturesAsync with mock HTTP) ─────

    private static readonly string SampleSoapResponse = """
        <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
          <soap:Body>
            <GetDepBoardWithDetailsResponse xmlns="http://thalesgroup.com/RTTI/2017-10-01/ldb/">
              <GetStationBoardResult>
                <locationName xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">London Paddington</locationName>
                <trainServices>
                  <service>
                    <std xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">14:30</std>
                    <etd xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">On time</etd>
                    <platform xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">1</platform>
                    <operator xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">GWR</operator>
                    <length xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">8</length>
                    <destination xmlns="http://thalesgroup.com/RTTI/2017-10-01/ldb/commontypes">
                      <location>
                        <locationName xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">Bristol Temple Meads</locationName>
                      </location>
                    </destination>
                    <subsequentCallingPoints>
                      <callingPointList>
                        <callingPoint>
                          <locationName xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">Reading</locationName>
                          <st xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">14:55</st>
                          <et xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">On time</et>
                        </callingPoint>
                      </callingPointList>
                    </subsequentCallingPoints>
                  </service>
                </trainServices>
              </GetStationBoardResult>
            </GetDepBoardWithDetailsResponse>
          </soap:Body>
        </soap:Envelope>
        """;

    private static readonly string NoServicesSoapResponse = """
        <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
          <soap:Body>
            <GetDepBoardWithDetailsResponse xmlns="http://thalesgroup.com/RTTI/2017-10-01/ldb/">
              <GetStationBoardResult>
                <locationName xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">London Paddington</locationName>
              </GetStationBoardResult>
            </GetDepBoardWithDetailsResponse>
          </soap:Body>
        </soap:Envelope>
        """;

    private static readonly string BusServicesSoapResponse = """
        <soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
          <soap:Body>
            <GetDepBoardWithDetailsResponse xmlns="http://thalesgroup.com/RTTI/2017-10-01/ldb/">
              <GetStationBoardResult>
                <locationName xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">Swindon</locationName>
                <busServices>
                  <service>
                    <std xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">15:00</std>
                    <etd xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">On time</etd>
                    <operator xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">GWR</operator>
                    <destination xmlns="http://thalesgroup.com/RTTI/2017-10-01/ldb/commontypes">
                      <location>
                        <locationName xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">Kemble</locationName>
                      </location>
                    </destination>
                    <subsequentCallingPoints>
                      <callingPointList>
                        <callingPoint>
                          <locationName xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">Kemble</locationName>
                          <st xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">15:30</st>
                          <et xmlns="http://thalesgroup.com/RTTI/2015-11-27/ldb/commonTypes">On time</et>
                        </callingPoint>
                      </callingPointList>
                    </subsequentCallingPoints>
                  </service>
                </busServices>
              </GetStationBoardResult>
            </GetDepBoardWithDetailsResponse>
          </soap:Body>
        </soap:Envelope>
        """;

    private static OpenLdbwsClient CreateClientWithResponse(string responseXml, HttpStatusCode statusCode = HttpStatusCode.OK)
    {
        var handler = new MockHttpMessageHandler(responseXml, statusCode);
        var httpClient = new HttpClient(handler);

        var factory = new Mock<IHttpClientFactory>();
        factory.Setup(f => f.CreateClient("OpenLdbws")).Returns(httpClient);

        var logger = new Mock<ILogger<OpenLdbwsClient>>();

        return new OpenLdbwsClient(factory.Object, logger.Object);
    }

    [Fact]
    public async Task FetchDepartures_ParsesSoapResponse_ExtractsFields()
    {
        var client = CreateClientWithResponse(SampleSoapResponse);

        var (departures, stationName) = await client.FetchDeparturesAsync("PAD", null, "test-key");

        Assert.Equal("London Paddington", stationName);
        Assert.NotNull(departures);
        Assert.Single(departures);

        var dep = departures[0];
        Assert.Equal("14:30", dep.AimedDepartureTime);
        Assert.Equal("On time", dep.ExpectedDepartureTime);
        Assert.Equal("1", dep.Platform);
        Assert.Equal("GWR", dep.Operator);
        Assert.Equal(8, dep.Carriages);
        Assert.Equal("Bristol Temple Meads", dep.DestinationName);
        Assert.Contains("Reading", dep.CallingAtList);
    }

    [Fact]
    public async Task FetchDepartures_NoServices_ReturnsNullDepartures()
    {
        var client = CreateClientWithResponse(NoServicesSoapResponse);

        var (departures, stationName) = await client.FetchDeparturesAsync("PAD", null, "test-key");

        Assert.Equal("London Paddington", stationName);
        Assert.Null(departures);
    }

    [Fact]
    public async Task FetchDepartures_BusServices_Parsed()
    {
        var client = CreateClientWithResponse(BusServicesSoapResponse);

        var (departures, stationName) = await client.FetchDeparturesAsync("SWI", null, "test-key");

        Assert.Equal("Swindon", stationName);
        Assert.NotNull(departures);
        Assert.Single(departures);
        Assert.Equal("15:00", departures[0].AimedDepartureTime);
        Assert.Equal("Kemble", departures[0].DestinationName);
    }

    [Fact]
    public async Task FetchDepartures_MalformedXml_ThrowsXmlException()
    {
        var client = CreateClientWithResponse("<not valid xml<<<");

        await Assert.ThrowsAsync<XmlException>(
            () => client.FetchDeparturesAsync("PAD", null, "test-key"));
    }

    /// <summary>
    /// Simple mock HttpMessageHandler that returns a canned response.
    /// </summary>
    private sealed class MockHttpMessageHandler : HttpMessageHandler
    {
        private readonly string _responseContent;
        private readonly HttpStatusCode _statusCode;

        public MockHttpMessageHandler(string responseContent, HttpStatusCode statusCode = HttpStatusCode.OK)
        {
            _responseContent = responseContent;
            _statusCode = statusCode;
        }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var response = new HttpResponseMessage(_statusCode)
            {
                Content = new StringContent(_responseContent, System.Text.Encoding.UTF8, "text/xml"),
            };
            return Task.FromResult(response);
        }
    }
}
