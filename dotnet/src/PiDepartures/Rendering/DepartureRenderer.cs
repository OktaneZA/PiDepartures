using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;
using PiDepartures.Config;
using PiDepartures.Models;
using SixLabors.Fonts;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Drawing.Processing;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Processing;

namespace PiDepartures.Rendering;

/// <summary>
/// Renders train departure board frames to a 256x64 grayscale framebuffer.
/// Uses SixLabors.ImageSharp for software rendering with dot-matrix bitmap fonts.
/// Thread-safe: rendering methods may be called from any thread.
/// </summary>
/// <remarks>
/// Layout (256 wide x 64 tall):
/// <list type="bullet">
///   <item>Row 0 (y=0,  h=10): First departure — time + destination, platform, status</item>
///   <item>Row 1 (y=12, h=10): "Calling at: " label + scrolling station list (DISP-03)</item>
///   <item>Row 2 (y=24, h=10): Second departure</item>
///   <item>Row 3 (y=36, h=10): Third departure</item>
///   <item>Row 4 (y=50, h=14): Clock — HH:MM (bold 20px) + :SS (bold tall 10px) + date (regular 10px)</item>
/// </list>
/// </remarks>
public sealed class DepartureRenderer : IDisposable
{
    /// <summary>Display width in pixels.</summary>
    public const int Width = 256;

    /// <summary>Display height in pixels.</summary>
    public const int Height = 64;

    private const int BitmapCacheMax = 256;

    private readonly ILogger<DepartureRenderer> _logger;
    private readonly Font _fontRegular;
    private readonly Font _fontBold;
    private readonly Font _fontBoldLarge;
    private readonly Font _fontBoldTall;
    private readonly FontCollection _fontCollection;

    // Per-screen scroll state keyed by screen identifier.
    private readonly ConcurrentDictionary<string, ScrollState> _scrollStates = new();

    // Bitmap text cache: key -> (width, height, pixel data). Bounded at BitmapCacheMax entries.
    // Uses ConcurrentDictionary for thread safety; eviction is approximate (not strict LRU)
    // to avoid lock contention in the render path.
    private readonly ConcurrentDictionary<string, (int Width, int Height, byte[] Pixels)> _bitmapCache = new();

    private bool _disposed;

    /// <summary>
    /// Initialises the renderer, loading dot-matrix fonts from the specified directory.
    /// </summary>
    /// <param name="fontsDirectory">
    /// Absolute or relative path to the directory containing the .ttf font files.
    /// Expected files: "Dot Matrix Regular.ttf", "Dot Matrix Bold.ttf", "Dot Matrix Bold Tall.ttf".
    /// </param>
    /// <param name="logger">Logger instance for diagnostic output.</param>
    /// <exception cref="FileNotFoundException">Thrown if a required font file is missing.</exception>
    public DepartureRenderer(string fontsDirectory, ILogger<DepartureRenderer> logger)
    {
        _logger = logger;
        _fontCollection = new FontCollection();

        var regularPath = Path.Combine(fontsDirectory, "Dot Matrix Regular.ttf");
        var boldPath = Path.Combine(fontsDirectory, "Dot Matrix Bold.ttf");
        var boldTallPath = Path.Combine(fontsDirectory, "Dot Matrix Bold Tall.ttf");

        if (!File.Exists(regularPath))
            throw new FileNotFoundException("Font file not found.", regularPath);
        if (!File.Exists(boldPath))
            throw new FileNotFoundException("Font file not found.", boldPath);
        if (!File.Exists(boldTallPath))
            throw new FileNotFoundException("Font file not found.", boldTallPath);

        var regularFamily = _fontCollection.Add(regularPath);
        var boldFamily = _fontCollection.Add(boldPath);
        var boldTallFamily = _fontCollection.Add(boldTallPath);

        _fontRegular = regularFamily.CreateFont(10);
        _fontBold = boldFamily.CreateFont(10);
        _fontBoldLarge = boldFamily.CreateFont(20);
        _fontBoldTall = boldTallFamily.CreateFont(10);

        _logger.LogDebug("DepartureRenderer initialised with fonts from {FontsDir}", fontsDirectory);
    }

    /// <summary>
    /// Renders a single departure board frame and returns the raw grayscale pixel data.
    /// </summary>
    /// <param name="departures">Current departure list, or null if no data is available yet.</param>
    /// <param name="stationName">Display name for the departure station.</param>
    /// <param name="errorCount">Consecutive API fetch error count (0 = healthy).</param>
    /// <param name="showDepartureNumbers">Whether to prefix rows with "1st", "2nd", "3rd".</param>
    /// <param name="firstDepartureBold">Whether the first departure row uses bold font (DISP-07).</param>
    /// <param name="config">Display configuration for refresh intervals and other settings.</param>
    /// <param name="screenId">
    /// Unique screen identifier for scroll state tracking (e.g. "screen1", "screen2").
    /// </param>
    /// <returns>
    /// A byte array of length <see cref="Width"/> * <see cref="Height"/> (16384) containing
    /// 8-bit grayscale pixel values (0 = black, 255 = lit/yellow).
    /// </returns>
    public byte[] RenderFrame(
        List<Departure>? departures,
        string stationName,
        int errorCount,
        bool showDepartureNumbers,
        bool firstDepartureBold,
        DisplayConfig config,
        string screenId = "default")
    {
        using var image = new Image<L8>(Width, Height, new L8(0));

        if (errorCount >= 3)
        {
            RenderConnectivityWarning(image, stationName, errorCount);
        }
        else if (departures is null || departures.Count == 0)
        {
            RenderBlankSignage(image, stationName);
        }
        else
        {
            RenderDepartures(image, departures, stationName, errorCount,
                showDepartureNumbers, firstDepartureBold, screenId);
        }

        return ExtractPixelData(image);
    }

    /// <summary>
    /// Resets the scroll state for the specified screen, causing the calling-at animation
    /// to restart from the beginning on the next frame.
    /// </summary>
    /// <param name="screenId">Screen identifier whose scroll state should be reset.</param>
    public void ResetScrollState(string screenId)
    {
        if (_scrollStates.TryGetValue(screenId, out var state))
            state.Reset();
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _bitmapCache.Clear();
        _scrollStates.Clear();
    }

    // -------------------------------------------------------------------------
    // Normal departure display
    // -------------------------------------------------------------------------

    private void RenderDepartures(
        Image<L8> image,
        List<Departure> departures,
        string stationName,
        int errorCount,
        bool showDepartureNumbers,
        bool firstDepartureBold,
        string screenId)
    {
        var firstFont = firstDepartureBold ? _fontBold : _fontRegular;

        // Row 0 (y=0): First departure
        RenderDepartureRow(image, departures[0], firstFont, "1st", 0, showDepartureNumbers);

        // Row 1 (y=12): Calling at + scrolling stations
        if (errorCount > 0 && errorCount < 3)
        {
            // ARCH-02: stale data with no-signal overlay
            RenderNoSignalOverlay(image, errorCount, y: 12);
        }
        else
        {
            RenderCallingAtRow(image, departures[0].CallingAtList, screenId, y: 12);
        }

        // Row 2 (y=24): Second departure
        if (departures.Count > 1)
            RenderDepartureRow(image, departures[1], _fontRegular, "2nd", 24, showDepartureNumbers);

        // Row 3 (y=36): Third departure
        if (departures.Count > 2)
            RenderDepartureRow(image, departures[2], _fontRegular, "3rd", 36, showDepartureNumbers);

        // Row 4 (y=50): Clock
        RenderClock(image, y: 50);
    }

    private void RenderDepartureRow(
        Image<L8> image, Departure dep, Font font, string position, int y,
        bool showNumbers)
    {
        // Left side: time + destination
        var aimed = dep.AimedDepartureTime;
        var dest = dep.DestinationName;
        var trainText = showNumbers
            ? $"{position}  {aimed}  {dest}"
            : $"{aimed}  {dest}";

        DrawCachedText(image, trainText, font, 0, y);

        // Right side: status
        var statusText = FormatStatus(dep);
        if (!string.IsNullOrEmpty(statusText))
        {
            var (sw, _, _) = GetCachedBitmap(statusText, _fontRegular);
            DrawCachedText(image, statusText, _fontRegular, Width - sw, y);
        }

        // Between: platform
        if (!string.IsNullOrEmpty(dep.Platform))
        {
            var platLabel = dep.Platform.Equals("BUS", StringComparison.OrdinalIgnoreCase)
                ? "BUS"
                : $"Plat {dep.Platform}";

            var (sw, _, _) = GetCachedBitmap("Exp 00:00", _fontRegular);
            var (pw, _, _) = GetCachedBitmap(platLabel, _fontRegular);
            DrawCachedText(image, platLabel, _fontRegular, Width - sw - pw - 5, y);
        }
    }

    private static string FormatStatus(Departure dep)
    {
        var exp = dep.ExpectedDepartureTime;
        if (string.IsNullOrEmpty(exp))
            return "";
        if (exp == "On time") return "On time";
        if (exp == "Cancelled") return "Cancelled";
        if (exp == "Delayed") return "Delayed";
        // If expected differs from aimed, show "Exp HH:MM"
        return dep.AimedDepartureTime == exp ? "On time" : $"Exp {exp}";
    }

    // -------------------------------------------------------------------------
    // Calling-at row with scroll animation (DISP-03)
    // -------------------------------------------------------------------------

    private void RenderCallingAtRow(Image<L8> image, string stations, string screenId, int y)
    {
        // "Calling at: " label (static)
        DrawCachedText(image, "Calling at: ", _fontRegular, 0, y);

        if (string.IsNullOrEmpty(stations))
            return;

        var (labelW, _, _) = GetCachedBitmap("Calling at: ", _fontRegular);
        var (txtW, txtH, txtPixels) = GetCachedBitmap(stations, _fontRegular);

        var state = _scrollStates.GetOrAdd(screenId, _ => new ScrollState());

        // Clip region for scrolling text: right of label to edge of screen
        var clipX = labelW;
        var clipWidth = Width - labelW;

        if (state.HasElevated != 0)
        {
            // Phase 2: horizontal scroll
            var drawX = clipX + state.PixelsLeft - 1;
            BlitCachedText(image, txtW, txtH, txtPixels, drawX, y, clipX, clipWidth);

            if (-state.PixelsLeft > txtW && state.PauseCount < 8)
            {
                state.PauseCount++;
                state.PixelsLeft = 0;
                state.HasElevated = 0;
            }
            else
            {
                state.PauseCount = 0;
                state.PixelsLeft--;
            }
        }
        else
        {
            // Phase 1: vertical scroll up into position
            var drawY = y + txtH - state.PixelsUp;
            BlitCachedText(image, txtW, txtH, txtPixels, clipX, drawY, clipX, clipWidth);

            if (state.PixelsUp == txtH)
            {
                state.PauseCount++;
                if (state.PauseCount > 20)
                {
                    state.HasElevated = 1;
                    state.PixelsUp = 0;
                }
            }
            else
            {
                state.PixelsUp++;
            }
        }
    }

    // -------------------------------------------------------------------------
    // Blank signage (no departures)
    // -------------------------------------------------------------------------

    private void RenderBlankSignage(Image<L8> image, string stationName)
    {
        // Row 0: "Welcome to" centred
        var (ww, _, _) = GetCachedBitmap("Welcome to", _fontBold);
        DrawCachedText(image, "Welcome to", _fontBold, (Width - ww) / 2, 0);

        // Row 1 (y=12): station name centred
        var (sw, _, _) = GetCachedBitmap(stationName, _fontBold);
        DrawCachedText(image, stationName, _fontBold, (Width - sw) / 2, 12);

        // Row 2 (y=24): dots
        DrawCachedText(image, ".  .  .", _fontBold, 0, 24);

        // Row 4 (y=50): clock
        RenderClock(image, y: 50);
    }

    // -------------------------------------------------------------------------
    // Connectivity warning (3+ failures) — ARCH-03
    // -------------------------------------------------------------------------

    private void RenderConnectivityWarning(Image<L8> image, string stationName, int errorCount)
    {
        // Station name centred
        var (sw, _, _) = GetCachedBitmap(stationName, _fontBold);
        DrawCachedText(image, stationName, _fontBold, (Width - sw) / 2, 0);

        // Warning message
        var msg = $"No network ({errorCount} attempts)";
        DrawCachedText(image, msg, _fontRegular, 0, 16);

        // Clock
        RenderClock(image, y: 50);
    }

    // -------------------------------------------------------------------------
    // No-signal overlay (ARCH-02: 1-2 errors with stale data)
    // -------------------------------------------------------------------------

    private void RenderNoSignalOverlay(Image<L8> image, int errorCount, int y)
    {
        var msg = $"No signal ({errorCount}x)";
        var (mw, _, _) = GetCachedBitmap(msg, _fontRegular);
        DrawCachedText(image, msg, _fontRegular, Width - mw, y);
    }

    // -------------------------------------------------------------------------
    // Clock row (DISP-09)
    // -------------------------------------------------------------------------

    private void RenderClock(Image<L8> image, int y)
    {
        var now = DateTime.Now;
        var hmText = $"{now.Hour:D2}:{now.Minute:D2}";
        var sText = $":{now.Second:D2}";
        var dateText = FormatOrdinalDate(now);

        var (w1, clockH, _) = GetCachedBitmap(hmText, _fontBoldLarge);
        // Measure seconds width using fixed ":00" to keep layout stable
        var (w2, _, _) = GetCachedBitmap(":00", _fontBoldTall);
        var (wDate, dateH, _) = GetCachedBitmap(dateText, _fontRegular);

        const int gap = 6; // pixels between time and date
        var totalW = w1 + w2 + gap + wDate;
        var x = (Width - totalW) / 2;

        DrawCachedText(image, hmText, _fontBoldLarge, x, y);
        DrawCachedText(image, sText, _fontBoldTall, x + w1, y + 5);

        var dateY = y + (clockH - dateH) / 2;
        DrawCachedText(image, dateText, _fontRegular, x + w1 + w2 + gap, dateY);
    }

    /// <summary>
    /// Formats a date as "Ddd DDth Month" (e.g. "Fri 13th March") per DISP-09.
    /// </summary>
    internal static string FormatOrdinalDate(DateTime dt)
    {
        var day = dt.Day;
        var suffix = (day % 100) is >= 11 and <= 13
            ? "th"
            : (day % 10) switch
            {
                1 => "st",
                2 => "nd",
                3 => "rd",
                _ => "th"
            };
        return $"{dt:ddd} {day}{suffix} {dt:MMMM}";
    }

    // -------------------------------------------------------------------------
    // Bitmap text cache (ARCH-09, P-02)
    // -------------------------------------------------------------------------

    private (int Width, int Height, byte[] Pixels) GetCachedBitmap(string text, Font font)
    {
        var key = $"{text}\0{font.Family.Name}\0{font.Size}";

        if (_bitmapCache.TryGetValue(key, out var cached))
            return cached;

        // Measure text bounds
        var options = new TextOptions(font);
        var bounds = TextMeasurer.MeasureBounds(text, options);
        var w = Math.Max(1, (int)MathF.Ceiling(bounds.Right));
        var h = Math.Max(1, (int)MathF.Ceiling(bounds.Bottom));

        // Render text to a temporary L8 image
        using var temp = new Image<L8>(w, h, new L8(0));
        temp.Mutate(ctx => ctx.DrawText(text, font, Color.White, new PointF(0, 0)));

        // Extract pixel data
        var pixels = new byte[w * h];
        temp.ProcessPixelRows(accessor =>
        {
            for (var row = 0; row < accessor.Height; row++)
            {
                var span = accessor.GetRowSpan(row);
                for (var col = 0; col < span.Length; col++)
                {
                    pixels[row * w + col] = span[col].PackedValue;
                }
            }
        });

        var entry = (w, h, pixels);

        // Enforce cache size limit with approximate eviction
        if (_bitmapCache.Count >= BitmapCacheMax)
        {
            // Evict a single arbitrary entry to make room
            foreach (var existingKey in _bitmapCache.Keys)
            {
                _bitmapCache.TryRemove(existingKey, out _);
                break;
            }
        }

        _bitmapCache.TryAdd(key, entry);
        return entry;
    }

    // -------------------------------------------------------------------------
    // Drawing helpers
    // -------------------------------------------------------------------------

    /// <summary>
    /// Draws cached text onto the image at the specified position.
    /// Pixels are clipped to the image bounds.
    /// </summary>
    private void DrawCachedText(Image<L8> image, string text, Font font, int x, int y)
    {
        var (w, h, pixels) = GetCachedBitmap(text, font);
        BlitPixels(image, w, h, pixels, x, y, 0, Width);
    }

    /// <summary>
    /// Blits cached text pixels onto the image within a horizontal clip region.
    /// Used for the scrolling calling-at text where content must be masked to
    /// the area right of the "Calling at:" label.
    /// </summary>
    private static void BlitCachedText(
        Image<L8> image, int srcW, int srcH, byte[] srcPixels,
        int destX, int destY, int clipX, int clipWidth)
    {
        BlitPixels(image, srcW, srcH, srcPixels, destX, destY, clipX, clipWidth);
    }

    /// <summary>
    /// Copies source pixel data onto the target image, respecting image bounds
    /// and an optional horizontal clip region [clipX, clipX + clipWidth).
    /// </summary>
    private static void BlitPixels(
        Image<L8> image, int srcW, int srcH, byte[] srcPixels,
        int destX, int destY, int clipX, int clipWidth)
    {
        image.ProcessPixelRows(accessor =>
        {
            var imgW = accessor.Width;
            var imgH = accessor.Height;
            var clipRight = Math.Min(clipX + clipWidth, imgW);

            for (var row = 0; row < srcH; row++)
            {
                var dy = destY + row;
                if (dy < 0 || dy >= imgH)
                    continue;

                var destRow = accessor.GetRowSpan(dy);
                var srcOffset = row * srcW;

                for (var col = 0; col < srcW; col++)
                {
                    var dx = destX + col;
                    if (dx < clipX || dx >= clipRight)
                        continue;

                    var val = srcPixels[srcOffset + col];
                    if (val > 0)
                        destRow[dx] = new L8(val);
                }
            }
        });
    }

    /// <summary>
    /// Extracts all pixel data from an L8 image into a flat byte array.
    /// </summary>
    private static byte[] ExtractPixelData(Image<L8> image)
    {
        var buffer = new byte[Width * Height];
        image.ProcessPixelRows(accessor =>
        {
            for (var row = 0; row < accessor.Height; row++)
            {
                var span = accessor.GetRowSpan(row);
                var offset = row * Width;
                for (var col = 0; col < span.Length; col++)
                {
                    buffer[offset + col] = span[col].PackedValue;
                }
            }
        });
        return buffer;
    }
}
