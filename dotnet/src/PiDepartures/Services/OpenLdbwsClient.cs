namespace PiDepartures.Services;

using System.Security;
using System.Xml;
using System.Xml.Linq;
using Microsoft.Extensions.Logging;
using PiDepartures.Models;

/// <summary>
/// SOAP client for the National Rail OpenLDBWS departure board API.
/// Builds a raw SOAP XML envelope, posts it via <see cref="HttpClient"/>,
/// and parses the XML response into <see cref="Departure"/> objects.
/// </summary>
/// <remarks>
/// Requirements: ARCH-01, ARCH-10, SEC-01, SEC-06, SEC-07.
/// </remarks>
public sealed class OpenLdbwsClient
{
    /// <summary>OpenLDBWS SOAP endpoint. HTTPS enforced, no HTTP fallback (SEC-06).</summary>
    private const string ApiUrl =
        "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx";

    /// <summary>Exponential backoff initial delay in seconds (ARCH-01).</summary>
    private const double BackoffInitial = 2.0;

    /// <summary>Maximum backoff delay in seconds (ARCH-01).</summary>
    private const double BackoffMax = 120.0;

    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<OpenLdbwsClient> _logger;

    /// <summary>
    /// Initializes a new instance of the <see cref="OpenLdbwsClient"/> class.
    /// </summary>
    /// <param name="httpClientFactory">Factory for creating <see cref="HttpClient"/> instances.</param>
    /// <param name="logger">Logger instance. The API key is never written to logs (SEC-01).</param>
    public OpenLdbwsClient(IHttpClientFactory httpClientFactory, ILogger<OpenLdbwsClient> logger)
    {
        _httpClientFactory = httpClientFactory ?? throw new ArgumentNullException(nameof(httpClientFactory));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <summary>
    /// Fetches live departures from the OpenLDBWS SOAP API.
    /// </summary>
    /// <param name="station">Three-letter CRS code for the departure station.</param>
    /// <param name="destination">Optional CRS code to filter departures by destination.</param>
    /// <param name="apiKey">OpenLDBWS API key. Never logged (SEC-01).</param>
    /// <param name="timeOffset">Minutes offset from now. Default "0".</param>
    /// <param name="rows">Maximum number of departures to request. Default 10.</param>
    /// <returns>
    /// A tuple of the parsed departure list (null if no services running) and the station display name.
    /// </returns>
    /// <exception cref="HttpRequestException">On network or HTTP-level failures.</exception>
    /// <exception cref="XmlException">On malformed or unexpected XML in the response.</exception>
    public async Task<(List<Departure>? Departures, string StationName)> FetchDeparturesAsync(
        string station,
        string? destination,
        string apiKey,
        string timeOffset = "0",
        int rows = 10)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(station);
        ArgumentException.ThrowIfNullOrWhiteSpace(apiKey);

        _logger.LogInformation("Fetching departures for {Station}", station);

        var soapXml = BuildSoapEnvelope(station, destination ?? "", apiKey, timeOffset, rows);

        using var client = _httpClientFactory.CreateClient("OpenLdbws");
        client.Timeout = TimeSpan.FromSeconds(15);

        using var content = new StringContent(soapXml, System.Text.Encoding.UTF8, "text/xml");
        using var response = await client.PostAsync(ApiUrl, content).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();

        var responseXml = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
        return ParseDepartures(responseXml);
    }

    /// <summary>
    /// Calculates the exponential backoff delay for a given failure count (ARCH-01).
    /// Formula: 2 * 2^(n-1), capped at 120 seconds.
    /// </summary>
    /// <param name="failureCount">Number of consecutive failures (1-based).</param>
    /// <returns>Delay in seconds.</returns>
    public static double BackoffDelay(int failureCount)
    {
        if (failureCount <= 0)
            return BackoffInitial;

        var delay = BackoffInitial * Math.Pow(2, failureCount - 1);
        return Math.Min(delay, BackoffMax);
    }

    /// <summary>
    /// Builds the SOAP XML envelope for a GetDepBoardWithDetails request.
    /// All config-derived values are XML-escaped to prevent injection (SEC-09).
    /// </summary>
    private static string BuildSoapEnvelope(
        string station,
        string destination,
        string apiKey,
        string timeOffset,
        int rows)
    {
        return
            """<x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" """ +
            """xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/" """ +
            """xmlns:typ4="http://thalesgroup.com/RTTI/2013-11-28/Token/types">""" +
            "<x:Header>" +
            "<typ4:AccessToken><typ4:TokenValue>" + SecurityElement.Escape(apiKey) + "</typ4:TokenValue></typ4:AccessToken>" +
            "</x:Header>" +
            "<x:Body>" +
            "<ldb:GetDepBoardWithDetailsRequest>" +
            "<ldb:numRows>" + SecurityElement.Escape(rows.ToString()) + "</ldb:numRows>" +
            "<ldb:crs>" + SecurityElement.Escape(station) + "</ldb:crs>" +
            "<ldb:timeOffset>" + SecurityElement.Escape(timeOffset) + "</ldb:timeOffset>" +
            "<ldb:filterCrs>" + SecurityElement.Escape(destination) + "</ldb:filterCrs>" +
            "<ldb:filterType>to</ldb:filterType>" +
            "<ldb:timeWindow>120</ldb:timeWindow>" +
            "</ldb:GetDepBoardWithDetailsRequest>" +
            "</x:Body>" +
            "</x:Envelope>";
    }

    /// <summary>
    /// Parses the SOAP XML response into a list of <see cref="Departure"/> objects.
    /// Uses local-name matching to avoid namespace complexity.
    /// </summary>
    private (List<Departure>? Departures, string StationName) ParseDepartures(string responseXml)
    {
        XDocument doc;
        try
        {
            doc = XDocument.Parse(responseXml);
        }
        catch (XmlException ex)
        {
            throw new XmlException($"Failed to parse SOAP XML response: {ex.Message}", ex);
        }

        var boardResult = doc.Descendants()
            .FirstOrDefault(e => e.Name.LocalName == "GetStationBoardResult");

        if (boardResult is null)
        {
            throw new XmlException("Unexpected SOAP response: missing GetStationBoardResult element");
        }

        var stationName = boardResult.Elements()
            .FirstOrDefault(e => e.Name.LocalName == "locationName")?.Value ?? "Unknown";

        var services = new List<XElement>();

        var trainServices = boardResult.Elements()
            .FirstOrDefault(e => e.Name.LocalName == "trainServices");
        if (trainServices is not null)
        {
            services.AddRange(trainServices.Elements().Where(e => e.Name.LocalName == "service"));
        }

        var busServices = boardResult.Elements()
            .FirstOrDefault(e => e.Name.LocalName == "busServices");
        if (busServices is not null)
        {
            services.AddRange(busServices.Elements().Where(e => e.Name.LocalName == "service"));
        }

        if (services.Count == 0)
        {
            return (null, stationName);
        }

        // Sort by departure time, handling midnight crossover (hours < 2 get +24).
        services = services
            .OrderBy(s =>
            {
                var std = GetChildValue(s, "std") ?? "00:00";
                var hour = int.Parse(std[..2]);
                var minute = int.Parse(std[3..5]);
                if (hour < 2)
                    hour += 24;
                return hour * 60 + minute;
            })
            .ToList();

        var departures = new List<Departure>();

        foreach (var service in services)
        {
            try
            {
                departures.Add(ParseService(service));
            }
            catch (Exception ex) when (ex is FormatException or NullReferenceException or ArgumentException)
            {
                _logger.LogWarning("Skipping malformed service: {Error}", ex.Message);
            }
        }

        return (departures, stationName);
    }

    /// <summary>
    /// Parses a single service XML element into a <see cref="Departure"/>.
    /// </summary>
    private static Departure ParseService(XElement service)
    {
        var departure = new Departure
        {
            AimedDepartureTime = GetChildValue(service, "std") ?? "",
            ExpectedDepartureTime = GetChildValue(service, "etd") ?? "",
            Platform = GetChildValue(service, "platform"),
            Operator = GetChildValue(service, "operator") ?? "",
            Carriages = int.TryParse(GetChildValue(service, "length"), out var len) ? len : 0,
        };

        // Destination: may be a single location or a list joined with " & ".
        var destElement = service.Elements()
            .FirstOrDefault(e => e.Name.LocalName == "destination");
        if (destElement is not null)
        {
            var locations = destElement.Elements()
                .Where(e => e.Name.LocalName == "location")
                .ToList();
            departure.DestinationName = string.Join(
                " & ",
                locations.Select(loc => RemoveBrackets(GetChildValue(loc, "locationName") ?? "")));
        }

        // Calling points
        departure.CallingAtList = BuildCallingAtList(service, departure.Operator, departure.Carriages);

        return departure;
    }

    /// <summary>
    /// Builds the "calling at" text from subsequent calling points.
    /// Handles single stops, multiple stops, and train splits.
    /// </summary>
    private static string BuildCallingAtList(XElement service, string operatorName, int carriages)
    {
        var serviceMessage = PrepareServiceMessage(operatorName);
        var carriageMessage = PrepareCarriagesMessage(carriages);

        var subCalling = service.Elements()
            .FirstOrDefault(e => e.Name.LocalName == "subsequentCallingPoints");

        if (subCalling is null)
        {
            var dest = service.Elements()
                .FirstOrDefault(e => e.Name.LocalName == "destination");
            var destName = dest?.Elements()
                .FirstOrDefault(e => e.Name.LocalName == "location")
                ?.Elements().FirstOrDefault(e => e.Name.LocalName == "locationName")?.Value ?? "";
            return JoinNonEmpty(" ", RemoveBrackets(destName) + " only.", serviceMessage, carriageMessage);
        }

        var callingPointLists = subCalling.Elements()
            .Where(e => e.Name.LocalName == "callingPointList")
            .ToList();

        if (callingPointLists.Count > 1)
        {
            // Train split: multiple sections joined with "with a portion going to".
            var sections = new List<string>();
            foreach (var cpl in callingPointLists)
            {
                var points = cpl.Elements()
                    .Where(e => e.Name.LocalName == "callingPoint")
                    .Select(cp => PrepareLocationName(cp))
                    .ToList();
                sections.Add(points.Count == 1 ? points[0] : JoinWithCommas(points));
            }

            return JoinNonEmpty(
                " ",
                string.Join(" with a portion going to ", sections),
                " -- ",
                serviceMessage,
                carriageMessage);
        }

        // Single calling point list.
        var stops = callingPointLists[0].Elements()
            .Where(e => e.Name.LocalName == "callingPoint")
            .Select(cp => PrepareLocationName(cp))
            .ToList();

        if (stops.Count == 1)
        {
            return JoinNonEmpty(" ", stops[0] + " only.", " -- ", serviceMessage, carriageMessage);
        }

        return JoinNonEmpty(" ", JoinWithCommas(stops) + ".", " -- ", serviceMessage, carriageMessage);
    }

    /// <summary>
    /// Strips parenthetical suffixes from station names (e.g. "Reading (Berks)" becomes "Reading").
    /// </summary>
    private static string RemoveBrackets(string name)
    {
        var idx = name.IndexOf(" (", StringComparison.Ordinal);
        return idx >= 0 ? name[..idx] : name;
    }

    /// <summary>
    /// Formats a calling point location name from an XML element.
    /// </summary>
    private static string PrepareLocationName(XElement callingPoint)
    {
        return RemoveBrackets(GetChildValue(callingPoint, "locationName") ?? "");
    }

    /// <summary>
    /// Formats the operator service message (e.g. "A Great Western Railway Service").
    /// </summary>
    private static string PrepareServiceMessage(string operatorName)
    {
        if (string.IsNullOrEmpty(operatorName))
            return "";

        var article = operatorName is "Elizabeth Line" or "Avanti West Coast" ? "An" : "A";
        return $"{article} {operatorName} Service";
    }

    /// <summary>
    /// Formats the carriages message (e.g. "formed of 8 coaches."), or empty if zero.
    /// </summary>
    private static string PrepareCarriagesMessage(int carriages)
    {
        return carriages == 0 ? "" : $"formed of {carriages} coaches.";
    }

    /// <summary>
    /// Joins a list with commas and replaces the last comma with "and".
    /// </summary>
    private static string JoinWithCommas(List<string> items)
    {
        if (items.Count == 0) return "";
        if (items.Count == 1) return items[0];

        var joined = string.Join(", ", items);
        var lastComma = joined.LastIndexOf(',');
        if (lastComma >= 0)
        {
            joined = string.Concat(joined.AsSpan(0, lastComma), " and", joined.AsSpan(lastComma + 1));
        }

        return joined;
    }

    /// <summary>
    /// Joins non-empty strings with the specified separator.
    /// </summary>
    private static string JoinNonEmpty(string separator, params string[] parts)
    {
        return string.Join(separator, parts.Where(p => !string.IsNullOrEmpty(p)));
    }

    /// <summary>
    /// Gets the text value of the first child element matching the given local name.
    /// </summary>
    private static string? GetChildValue(XElement parent, string localName)
    {
        return parent.Elements()
            .FirstOrDefault(e => e.Name.LocalName == localName)?.Value;
    }
}
