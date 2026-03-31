using System.Device.Gpio;
using System.Device.Spi;
using Microsoft.Extensions.Logging;

namespace PiDepartures.Hardware;

/// <summary>
/// SPI-connected SSD1322 256×64 4-bit grayscale OLED display driver.
/// Uses <c>System.Device.Gpio</c> and <c>System.Device.Spi</c> for hardware access.
/// </summary>
/// <remarks>
/// Wiring assumptions (directly matching luma.oled defaults):
/// <list type="bullet">
///   <item>SPI bus 0, chip-select 0</item>
///   <item>DC (data/command) = GPIO 24 (physical pin 18)</item>
///   <item>RST (reset)       = GPIO 25 (physical pin 22)</item>
/// </list>
/// </remarks>
public sealed class Ssd1322Spi : ISsd1322
{
    // --- Pin assignments ---------------------------------------------------
    private const int DcPin = 24;   // GPIO 24 — Data/Command
    private const int RstPin = 25;  // GPIO 25 — Reset

    // --- SSD1322 controller geometry ---------------------------------------
    // The SSD1322 controller addresses a 480-column space (in 4-bit pixels).
    // A 256-pixel-wide panel sits in columns 28..91 (each column = 4 pixels).
    private const int ColumnOffset = 0x1C; // 28
    private const int ColumnEnd = 0x5B;    // 91
    private const int RowStart = 0x00;
    private const int RowEnd = 0x3F;       // 63

    private const int SpiMaxChunkBytes = 4096;

    private readonly ILogger<Ssd1322Spi> _logger;
    private readonly int _rotation;
    private SpiDevice? _spi;
    private GpioController? _gpio;
    private bool _disposed;

    /// <summary>
    /// Initializes a new instance of the <see cref="Ssd1322Spi"/> class.
    /// The display is not usable until <see cref="Init"/> is called.
    /// </summary>
    /// <param name="logger">Logger instance.</param>
    /// <param name="rotation">
    /// Display rotation: 0 (normal), 1 (90° CW), 2 (180°), or 3 (270° CW).
    /// Only 0 and 2 are meaningful for this panel geometry.
    /// </param>
    /// <exception cref="ArgumentOutOfRangeException">
    /// Thrown when <paramref name="rotation"/> is not 0, 1, 2, or 3.
    /// </exception>
    public Ssd1322Spi(ILogger<Ssd1322Spi> logger, int rotation = 0)
    {
        if (rotation is < 0 or > 3)
            throw new ArgumentOutOfRangeException(nameof(rotation), rotation,
                "Rotation must be 0, 1, 2, or 3.");

        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        _rotation = rotation;
    }

    /// <inheritdoc />
    public int Width => 256;

    /// <inheritdoc />
    public int Height => 64;

    /// <inheritdoc />
    public void Init()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        _logger.LogInformation("SSD1322: Initializing on SPI0.0, DC=GPIO{Dc}, RST=GPIO{Rst}",
            DcPin, RstPin);

        // Open SPI bus 0, chip-select 0, 8 MHz, Mode0
        var spiSettings = new SpiConnectionSettings(0, 0)
        {
            ClockFrequency = 8_000_000,
            Mode = SpiMode.Mode0,
            DataBitLength = 8
        };
        _spi = SpiDevice.Create(spiSettings);

        _gpio = new GpioController();
        _gpio.OpenPin(DcPin, PinMode.Output);
        _gpio.OpenPin(RstPin, PinMode.Output);

        // Hardware reset
        _gpio.Write(RstPin, PinValue.High);
        Thread.Sleep(1);
        _gpio.Write(RstPin, PinValue.Low);
        Thread.Sleep(100);
        _gpio.Write(RstPin, PinValue.High);
        Thread.Sleep(100);

        // Determine remap bytes based on rotation
        byte remapA, remapB;
        if (_rotation is 0 or 1)
        {
            remapA = 0x14;
            remapB = 0x11;
        }
        else
        {
            // 180° / 270°: flip column and nibble order
            remapA = 0x06;
            remapB = 0x11;
        }

        // SSD1322 initialization command sequence
        SendCommand(0xFD, 0x12);             // Unlock commands
        SendCommand(0xAE);                   // Display OFF
        SendCommand(0xB3, 0x91);             // Clock divider / oscillator freq
        SendCommand(0xCA, 0x3F);             // Multiplex ratio = 63 (64 rows)
        SendCommand(0xA2, 0x00);             // Display offset = 0
        SendCommand(0xA1, 0x00);             // Start line = 0
        SendCommand(0xA0, remapA, remapB);   // Re-map & dual COM line mode
        SendCommand(0xB5, 0x00);             // GPIO = disabled
        SendCommand(0xAB, 0x01);             // Function selection (internal VDD)
        SendCommand(0xB4, 0xA0, 0xFD);      // Display enhancement A
        SendCommand(0xC1, 0x9F);             // Contrast current
        SendCommand(0xC7, 0x0F);             // Master contrast (max)
        SendCommand(0xB9);                   // Default linear grayscale table
        SendCommand(0xB1, 0xE2);             // Phase length
        SendCommand(0xD1, 0x82, 0x20);       // Display enhancement B
        SendCommand(0xBB, 0x1F);             // Pre-charge voltage
        SendCommand(0xB6, 0x08);             // Second pre-charge period
        SendCommand(0xBE, 0x07);             // VCOMH voltage
        SendCommand(0xA6);                   // Normal display (not inverted)
        SendCommand(0xAF);                   // Display ON

        _logger.LogInformation("SSD1322: Initialization complete (rotation={Rotation})", _rotation);
    }

    /// <inheritdoc />
    public void Display(byte[] frameBuffer)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(frameBuffer);

        if (frameBuffer.Length != Width * Height)
        {
            throw new ArgumentException(
                $"Frame buffer must be {Width * Height} bytes, got {frameBuffer.Length}.",
                nameof(frameBuffer));
        }

        // Convert 8-bit grayscale to 4-bit packed (two pixels per byte).
        // High nibble = left pixel, low nibble = right pixel.
        int packedLength = Width * Height / 2; // 8192
        byte[] packed = new byte[packedLength];

        for (int i = 0; i < packedLength; i++)
        {
            int srcIdx = i * 2;
            byte hi = (byte)(frameBuffer[srcIdx] >> 4);       // 8-bit -> 4-bit
            byte lo = (byte)(frameBuffer[srcIdx + 1] >> 4);
            packed[i] = (byte)((hi << 4) | lo);
        }

        // Set column address (28..91 for 256 pixels)
        SendCommand(0x15, ColumnOffset, ColumnEnd);
        // Set row address (0..63)
        SendCommand(0x75, RowStart, RowEnd);
        // Write RAM command, then pixel data
        SendCommand(0x5C);
        SendData(packed);
    }

    /// <inheritdoc />
    public void Clear()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        Display(new byte[Width * Height]);
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;

        try
        {
            // Turn display off before releasing hardware
            if (_spi is not null && _gpio is not null)
            {
                SendCommand(0xAE); // Display OFF
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "SSD1322: Error sending display-off during dispose");
        }

        _spi?.Dispose();
        _spi = null;

        if (_gpio is not null)
        {
            _gpio.ClosePin(DcPin);
            _gpio.ClosePin(RstPin);
            _gpio.Dispose();
            _gpio = null;
        }

        _logger.LogInformation("SSD1322: Disposed");
    }

    // -------------------------------------------------------------------
    //  Private helpers
    // -------------------------------------------------------------------

    /// <summary>
    /// Sends one or more command bytes to the SSD1322 with DC held low.
    /// </summary>
    private void SendCommand(params byte[] data)
    {
        EnsureHardwareReady();
        _gpio!.Write(DcPin, PinValue.Low);
        _spi!.Write(data);
    }

    /// <summary>
    /// Sends a data payload to the SSD1322 with DC held high.
    /// Large payloads are chunked to stay within SPI transfer limits.
    /// </summary>
    private void SendData(byte[] data)
    {
        EnsureHardwareReady();
        _gpio!.Write(DcPin, PinValue.High);

        int offset = 0;
        while (offset < data.Length)
        {
            int chunkSize = Math.Min(SpiMaxChunkBytes, data.Length - offset);
            _spi!.Write(data.AsSpan(offset, chunkSize));
            offset += chunkSize;
        }
    }

    /// <summary>
    /// Throws if hardware has not been initialised or has been disposed.
    /// </summary>
    private void EnsureHardwareReady()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (_spi is null || _gpio is null)
        {
            throw new InvalidOperationException(
                "Display hardware not initialised. Call Init() before sending data.");
        }
    }
}
