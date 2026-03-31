namespace PiDepartures.Services;

using System.Diagnostics;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using PiDepartures.Config;
using PiDepartures.Hardware;
using PiDepartures.Rendering;

/// <summary>
/// Background service that drives the SSD1322 OLED display at the configured frame rate.
/// Reads departure data from <see cref="SharedState"/> each frame and renders via
/// <c>DepartureRenderer.RenderFrame()</c>. Handles blank-hours and restart requests.
/// </summary>
/// <remarks>
/// Requirements: ARCH-08, DISP-01, DISP-09.
/// </remarks>
public sealed class RenderService : BackgroundService
{
    private readonly SharedState _state;
    private readonly DisplayConfig _config;
    private readonly ISsd1322 _display;
    private readonly DepartureRenderer _renderer;
    private readonly IHostApplicationLifetime _lifetime;
    private readonly ILogger<RenderService> _logger;

    /// <summary>Parsed blank-hours start (inclusive), or -1 if blank hours are not configured.</summary>
    private readonly int _blankStart;

    /// <summary>Parsed blank-hours end (exclusive), or -1 if blank hours are not configured.</summary>
    private readonly int _blankEnd;

    /// <summary>
    /// Initializes a new instance of the <see cref="RenderService"/> class.
    /// </summary>
    /// <param name="state">Shared state containing departure data.</param>
    /// <param name="config">Display configuration.</param>
    /// <param name="display">SSD1322 display instance (real or null for headless mode).</param>
    /// <param name="lifetime">Host application lifetime, used to trigger restarts.</param>
    /// <param name="logger">Logger instance.</param>
    public RenderService(
        SharedState state,
        DisplayConfig config,
        ISsd1322 display,
        DepartureRenderer renderer,
        IHostApplicationLifetime lifetime,
        ILogger<RenderService> logger)
    {
        _state = state ?? throw new ArgumentNullException(nameof(state));
        _config = config ?? throw new ArgumentNullException(nameof(config));
        _display = display ?? throw new ArgumentNullException(nameof(display));
        _renderer = renderer ?? throw new ArgumentNullException(nameof(renderer));
        _lifetime = lifetime ?? throw new ArgumentNullException(nameof(lifetime));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));

        (_blankStart, _blankEnd) = ParseBlankHours(_config.ScreenBlankHours);
    }

    /// <inheritdoc />
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation(
            "RenderService starting: {Fps} FPS, blank hours={BlankHours}",
            _config.TargetFps,
            _config.ScreenBlankHours ?? "(none)");

        try
        {
            _display.Init();
            _logger.LogInformation("Display initialized");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to initialize display — cannot continue");
            _lifetime.StopApplication();
            return;
        }

        var frameDuration = TimeSpan.FromMilliseconds(1000.0 / _config.TargetFps);
        var stopwatch = Stopwatch.StartNew();

        while (!stoppingToken.IsCancellationRequested)
        {
            stopwatch.Restart();

            try
            {
                // Check if the portal requested a restart after config save.
                if (_state.RestartRequested)
                {
                    _logger.LogInformation("Restart requested — stopping application");
                    _lifetime.StopApplication();
                    return;
                }

                // Blank-hours: clear the display and skip rendering.
                if (IsInBlankHours(DateTime.Now.Hour))
                {
                    _display.Clear();
                    await Task.Delay(TimeSpan.FromSeconds(1), stoppingToken).ConfigureAwait(false);
                    continue;
                }

                var (departures, stationName, errorCount, epoch) = _state.GetSnapshot();

                // Render the frame. DepartureRenderer is expected to produce a
                // Width * Height byte array (one byte per pixel, 0-255 grayscale).
                var frameBuffer = _renderer.RenderFrame(
                    departures,
                    stationName,
                    errorCount,
                    _config.ShowDepartureNumbers,
                    _config.FirstDepartureBold,
                    _config);

                _display.Display(frameBuffer);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Render loop error");
            }

            // Maintain target frame rate.
            var elapsed = stopwatch.Elapsed;
            if (elapsed < frameDuration)
            {
                await Task.Delay(frameDuration - elapsed, stoppingToken).ConfigureAwait(false);
            }
        }

        // ARCH-08: clean shutdown — clear display.
        try
        {
            _display.Clear();
            _logger.LogInformation("Display cleared on shutdown");
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to clear display on shutdown");
        }

        _logger.LogInformation("RenderService stopped");
    }

    /// <inheritdoc />
    public override void Dispose()
    {
        _display.Dispose();
        base.Dispose();
    }

    /// <summary>
    /// Parses a blank-hours string in "HH-HH" format into start and end hours.
    /// Returns (-1, -1) if the value is null, empty, or malformed.
    /// </summary>
    /// <param name="blankHours">Blank-hours string (e.g. "01-06", "22-06").</param>
    /// <returns>Tuple of (start hour, end hour), or (-1, -1) if not configured.</returns>
    private static (int Start, int End) ParseBlankHours(string? blankHours)
    {
        if (string.IsNullOrWhiteSpace(blankHours))
            return (-1, -1);

        var parts = blankHours.Split('-');
        if (parts.Length != 2
            || !int.TryParse(parts[0], out var start)
            || !int.TryParse(parts[1], out var end)
            || start is < 0 or > 23
            || end is < 0 or > 23)
        {
            return (-1, -1);
        }

        return (start, end);
    }

    /// <summary>
    /// Returns true if the given hour falls within the configured blank-hours window.
    /// Handles midnight crossover (e.g. start=22, end=6 means 22, 23, 0, 1, 2, 3, 4, 5 are blank).
    /// </summary>
    /// <param name="currentHour">The current hour (0-23).</param>
    /// <returns>True if the display should be blanked.</returns>
    private bool IsInBlankHours(int currentHour)
    {
        if (_blankStart < 0)
            return false;

        if (_blankStart < _blankEnd)
        {
            // Simple range: e.g. 01-06 means hours 1, 2, 3, 4, 5 are blank.
            return currentHour >= _blankStart && currentHour < _blankEnd;
        }

        // Midnight crossover: e.g. 22-06 means 22, 23, 0, 1, 2, 3, 4, 5 are blank.
        return currentHour >= _blankStart || currentHour < _blankEnd;
    }
}
