namespace PiDepartures.Services;

using System.Xml;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PiDepartures.Config;

/// <summary>
/// Background service that periodically fetches live departures from the
/// OpenLDBWS API and writes results to <see cref="SharedState"/>.
/// Implements exponential backoff on failure (ARCH-01).
/// </summary>
/// <remarks>
/// Requirements: ARCH-01, ARCH-08, ARCH-10, SEC-01.
/// </remarks>
public sealed class FetchService : BackgroundService
{
    private readonly OpenLdbwsClient _client;
    private readonly SharedState _state;
    private readonly DisplayConfig _config;
    private readonly ILogger<FetchService> _logger;

    /// <summary>
    /// Initializes a new instance of the <see cref="FetchService"/> class.
    /// </summary>
    /// <param name="client">OpenLDBWS SOAP client.</param>
    /// <param name="state">Shared state written to on each successful fetch.</param>
    /// <param name="config">Display configuration containing station, API key, and refresh interval.</param>
    /// <param name="logger">Logger instance.</param>
    public FetchService(
        OpenLdbwsClient client,
        SharedState state,
        DisplayConfig config,
        ILogger<FetchService> logger)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _state = state ?? throw new ArgumentNullException(nameof(state));
        _config = config ?? throw new ArgumentNullException(nameof(config));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <inheritdoc />
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation(
            "FetchService starting: station={Station}, refresh={Refresh}s",
            _config.DepartureStation,
            _config.RefreshTime);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var (departures, stationName) = await _client.FetchDeparturesAsync(
                    _config.DepartureStation,
                    _config.DestinationStation,
                    _config.ApiKey,
                    timeOffset: "0",
                    rows: 10).ConfigureAwait(false);

                _state.Update(departures, stationName);
                _logger.LogInformation(
                    "Fetch OK: {Count} departures for {Station}",
                    departures?.Count ?? 0,
                    stationName);

                await Task.Delay(TimeSpan.FromSeconds(_config.RefreshTime), stoppingToken)
                    .ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                // ARCH-08: clean shutdown — exit the loop without logging an error.
                break;
            }
            catch (Exception ex) when (ex is HttpRequestException or XmlException)
            {
                // Expected transient failures: network errors and malformed XML.
                var errorCount = _state.IncrementError();
                var delay = OpenLdbwsClient.BackoffDelay(errorCount);
                _logger.LogWarning(
                    "Fetch failed ({ErrorType}): {Message} — retry in {Delay:F0}s (attempt {Count})",
                    ex.GetType().Name,
                    ex.Message,
                    delay,
                    errorCount);

                await Task.Delay(TimeSpan.FromSeconds(delay), stoppingToken)
                    .ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                // Unexpected exception: log as error and rethrow so the host can handle it.
                _logger.LogError(ex, "FetchService encountered an unexpected error");
                throw;
            }
        }

        _logger.LogInformation("FetchService stopped");
    }
}
