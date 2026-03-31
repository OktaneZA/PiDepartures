using System.Diagnostics;
using PiDepartures.Config;
using PiDepartures.Services;

namespace PiDepartures.Portal;

/// <summary>
/// Maps Minimal API routes for the train-display configuration portal.
/// Authenticated endpoints are protected by <see cref="PortalAuthFilter"/>;
/// health and system-info endpoints are public.
/// </summary>
public static class PortalEndpoints
{
    private const string Mask = "••••••••";
    private const string DefaultConfigPath = "/etc/train-display/config";

    /// <summary>
    /// Registers all portal routes on the given <see cref="WebApplication"/>.
    /// </summary>
    /// <param name="app">The web application to register routes on.</param>
    /// <param name="sharedState">Shared departure state for the status endpoint.</param>
    public static void MapPortalEndpoints(this WebApplication app, SharedState sharedState)
    {
        var portal = app.MapGroup("").AddEndpointFilter<PortalAuthFilter>();

        // GET / — serve the single-page portal HTML.
        portal.MapGet("/", () =>
            Results.File("wwwroot/index.html", "text/html"));

        // GET /config — returns current config as JSON with the API key masked.
        portal.MapGet("/config", () =>
        {
            var raw = TryLoadConfig();
            if (raw.TryGetValue("API_KEY", out var apiKey) && !string.IsNullOrEmpty(apiKey))
                raw["API_KEY"] = Mask;
            if (raw.TryGetValue("PORTAL_PASSWORD", out var pw) && !string.IsNullOrEmpty(pw))
                raw["PORTAL_PASSWORD"] = Mask;
            return Results.Json(raw);
        });

        // POST /save — validate and persist config, then signal a restart.
        portal.MapPost("/save", (HttpContext ctx) =>
        {
            var form = ctx.Request.Form;
            var raw = TryLoadConfig();
            var newCfg = new Dictionary<string, string>(raw, StringComparer.OrdinalIgnoreCase);

            // ── Journey settings ────────────────────────────────────────
            newCfg["DEPARTURE_STATION"] =
                (form["DEPARTURE_STATION"].ToString()).Trim().ToUpperInvariant();

            var dest = (form["DESTINATION_STATION"].ToString()).Trim().ToUpperInvariant();
            if (!string.IsNullOrEmpty(dest))
                newCfg["DESTINATION_STATION"] = dest;
            else
                newCfg.Remove("DESTINATION_STATION");

            // ── Filters ─────────────────────────────────────────────────
            var platform = (form["PLATFORM_FILTER"].ToString()).Trim();
            if (!string.IsNullOrEmpty(platform))
                newCfg["PLATFORM_FILTER"] = platform;
            else
                newCfg.Remove("PLATFORM_FILTER");

            var blankHours = (form["SCREEN_BLANK_HOURS"].ToString()).Trim();
            if (!string.IsNullOrEmpty(blankHours))
                newCfg["SCREEN_BLANK_HOURS"] = blankHours;
            else
                newCfg.Remove("SCREEN_BLANK_HOURS");

            // ── Display settings ────────────────────────────────────────
            newCfg["REFRESH_TIME"] = (form["REFRESH_TIME"].ToString()).Trim();
            if (string.IsNullOrEmpty(newCfg["REFRESH_TIME"]))
                newCfg["REFRESH_TIME"] = "120";

            newCfg["SCREEN_ROTATION"] = (form["SCREEN_ROTATION"].ToString()).Trim();
            if (string.IsNullOrEmpty(newCfg["SCREEN_ROTATION"]))
                newCfg["SCREEN_ROTATION"] = "2";

            newCfg["FIRST_DEPARTURE_BOLD"] =
                form.ContainsKey("FIRST_DEPARTURE_BOLD") ? "true" : "false";
            newCfg["SHOW_DEPARTURE_NUMBERS"] =
                form.ContainsKey("SHOW_DEPARTURE_NUMBERS") ? "true" : "false";
            newCfg["DUAL_SCREEN"] =
                form.ContainsKey("DUAL_SCREEN") ? "true" : "false";

            // ── Portal settings ─────────────────────────────────────────
            newCfg["PORTAL_PORT"] = (form["PORTAL_PORT"].ToString()).Trim();
            if (string.IsNullOrEmpty(newCfg["PORTAL_PORT"]))
                newCfg["PORTAL_PORT"] = "8080";

            // API_KEY: only overwrite if user supplied a new (non-masked) value.
            var apiKey = (form["API_KEY"].ToString()).Trim();
            if (!string.IsNullOrEmpty(apiKey) && apiKey != Mask)
                newCfg["API_KEY"] = apiKey;

            // Password: hash if changed, clear if blanked.
            var newPw = (form["PORTAL_PASSWORD"].ToString()).Trim();
            if (!string.IsNullOrEmpty(newPw) && newPw != Mask)
                newCfg["PORTAL_PASSWORD"] = ConfigLoader.HashPassword(newPw);
            else if (string.IsNullOrEmpty(newPw))
                newCfg["PORTAL_PASSWORD"] = "";

            // ── Validate ────────────────────────────────────────────────
            var errors = ConfigLoader.ValidatePortalConfig(newCfg);
            if (errors.Count > 0)
            {
                var joined = Uri.EscapeDataString(string.Join(" | ", errors));
                return Results.Redirect($"/?errors={joined}");
            }

            // ── Save ────────────────────────────────────────────────────
            try
            {
                ConfigLoader.SaveRawConfig(newCfg, DefaultConfigPath);
            }
            catch (Exception ex)
            {
                var msg = Uri.EscapeDataString($"Save failed: {ex.Message}");
                return Results.Redirect($"/?errors={msg}");
            }

            sharedState.RestartRequested = true;
            return Results.Redirect("/?saved=1");
        });

        // GET /status — live departure state as JSON.
        portal.MapGet("/status", () =>
        {
            var (departures, stationName, errorCount, _) = sharedState.GetSnapshot();
            return Results.Json(new
            {
                station_name = stationName,
                departures = departures?.Take(5).Select(d => new
                {
                    aimed = d.AimedDepartureTime,
                    destination = d.DestinationName,
                    platform = d.Platform,
                    expected = d.ExpectedDepartureTime,
                }),
                error_count = errorCount,
            });
        });

        // ── Public endpoints (no auth) ──────────────────────────────────
        app.MapGet("/sysinfo", () =>
        {
            string? ssid = null;
            int? signalDbm = null;

            try
            {
                var psi = new ProcessStartInfo("iwgetid", "-r")
                {
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                };
                using var proc = Process.Start(psi);
                if (proc is not null)
                {
                    ssid = proc.StandardOutput.ReadToEnd().Trim();
                    proc.WaitForExit(3000);
                    if (string.IsNullOrEmpty(ssid))
                        ssid = null;
                }
            }
            catch
            {
                // Not running on Linux or iwgetid unavailable — leave null.
            }

            try
            {
                foreach (var line in File.ReadAllLines("/proc/net/wireless"))
                {
                    if (!line.Contains("wlan"))
                        continue;
                    var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                    signalDbm = (int)double.Parse(parts[3].TrimEnd('.'));
                    break;
                }
            }
            catch
            {
                // Not running on Linux or wlan info unavailable — leave null.
            }

            return Results.Json(new { ssid, signal_dbm = signalDbm });
        });

        app.MapGet("/health", () => Results.Json(new { ok = true }));
    }

    /// <summary>
    /// Attempts to load the raw configuration file, returning an empty dictionary on failure.
    /// </summary>
    private static Dictionary<string, string> TryLoadConfig()
    {
        try
        {
            return ConfigLoader.LoadRawConfig();
        }
        catch
        {
            return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }
    }
}
