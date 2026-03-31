using Microsoft.Extensions.Logging;

namespace PiDepartures.Hardware;

/// <summary>
/// Headless implementation of <see cref="ISsd1322"/> that performs no hardware I/O.
/// Useful for development and testing on machines without SPI hardware.
/// </summary>
public sealed class NullDisplay : ISsd1322
{
    private readonly ILogger<NullDisplay> _logger;

    /// <summary>
    /// Initializes a new instance of the <see cref="NullDisplay"/> class.
    /// </summary>
    /// <param name="logger">Logger instance for diagnostic output.</param>
    public NullDisplay(ILogger<NullDisplay> logger)
    {
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <inheritdoc />
    public int Width => 256;

    /// <inheritdoc />
    public int Height => 64;

    /// <inheritdoc />
    public void Init()
    {
        _logger.LogDebug("NullDisplay: Init (no-op)");
    }

    /// <inheritdoc />
    public void Display(byte[] frameBuffer)
    {
        ArgumentNullException.ThrowIfNull(frameBuffer);

        if (frameBuffer.Length != Width * Height)
        {
            throw new ArgumentException(
                $"Frame buffer must be {Width * Height} bytes, got {frameBuffer.Length}.",
                nameof(frameBuffer));
        }

        _logger.LogDebug("NullDisplay: frame rendered");
    }

    /// <inheritdoc />
    public void Clear()
    {
        _logger.LogDebug("NullDisplay: Clear (no-op)");
    }

    /// <inheritdoc />
    public void Dispose()
    {
        // Nothing to dispose.
    }
}
