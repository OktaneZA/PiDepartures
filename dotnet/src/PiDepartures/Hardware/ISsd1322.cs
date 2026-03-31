namespace PiDepartures.Hardware;

/// <summary>
/// Interface for an SSD1322-based 256×64 4-bit grayscale OLED display.
/// </summary>
public interface ISsd1322 : IDisposable
{
    /// <summary>
    /// Display width in pixels. Always 256 for the SSD1322.
    /// </summary>
    int Width { get; }

    /// <summary>
    /// Display height in pixels. Always 64 for the SSD1322.
    /// </summary>
    int Height { get; }

    /// <summary>
    /// Initializes the display hardware: performs reset, sends the SSD1322
    /// command sequence, and turns the display on.
    /// </summary>
    void Init();

    /// <summary>
    /// Sends a full 256×64 grayscale frame to the display.
    /// Each byte in <paramref name="frameBuffer"/> represents one pixel
    /// with brightness 0 (off) to 255 (full on). The buffer is packed
    /// to 4-bit grayscale internally before transmission.
    /// </summary>
    /// <param name="frameBuffer">
    /// A byte array of length <see cref="Width"/> × <see cref="Height"/> (16384).
    /// Pixel order is left-to-right, top-to-bottom.
    /// </param>
    /// <exception cref="ArgumentException">
    /// Thrown when <paramref name="frameBuffer"/> length is not 16384.
    /// </exception>
    void Display(byte[] frameBuffer);

    /// <summary>
    /// Blanks the display by writing an all-zero frame.
    /// </summary>
    void Clear();
}
