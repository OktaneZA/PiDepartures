using PiDepartures.Config;
using PiDepartures.Hardware;
using PiDepartures.Portal;
using PiDepartures.Rendering;
using PiDepartures.Services;

// ---------------------------------------------------------------------------
// Load configuration from environment variables (systemd EnvironmentFile)
// ---------------------------------------------------------------------------
var config = ConfigLoader.LoadConfig();

var builder = WebApplication.CreateBuilder(args);

// Override Kestrel to listen on the portal port
builder.WebHost.UseUrls($"http://0.0.0.0:{config.PortalPort}");

// ---------------------------------------------------------------------------
// Register services
// ---------------------------------------------------------------------------
builder.Services.AddSingleton(config);
builder.Services.AddSingleton<SharedState>();
builder.Services.AddSingleton<DepartureRenderer>();
builder.Services.AddHttpClient<OpenLdbwsClient>();

// Display hardware — real SPI or headless null driver
if (config.Headless)
{
    builder.Services.AddSingleton<ISsd1322, NullDisplay>();
    builder.Logging.AddConsole();
}
else
{
    builder.Services.AddSingleton<ISsd1322>(sp =>
        new Ssd1322Spi(sp.GetRequiredService<ILogger<Ssd1322Spi>>(), config.ScreenRotation));
}

// Background services
builder.Services.AddHostedService<FetchService>();
builder.Services.AddHostedService<RenderService>();

// Static files for portal HTML
builder.Services.AddDirectoryBrowser();

var app = builder.Build();

// ---------------------------------------------------------------------------
// Portal routes
// ---------------------------------------------------------------------------
app.UseStaticFiles();

if (config.PortalEnabled)
{
    app.MapPortalEndpoints(app.Services.GetRequiredService<SharedState>());
    app.Logger.LogInformation("Portal enabled on http://0.0.0.0:{Port}", config.PortalPort);
}
else
{
    // Health endpoint always available even if portal is disabled
    app.MapGet("/health", () => Results.Json(new { ok = true }));
    app.Logger.LogInformation("Portal disabled (PORTAL_ENABLED=false)");
}

app.Logger.LogInformation(
    "Starting Train Departure Display (.NET) — station={Station} headless={Headless}",
    config.DepartureStation, config.Headless);

app.Run();
