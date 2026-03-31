namespace PiDepartures.Rendering;

/// <summary>
/// Tracks horizontal and vertical scroll position for the calling-points ticker row.
/// Used by <see cref="DepartureRenderer"/> to animate the DISP-03 scroll sequence:
/// text scrolls up into position, pauses, then scrolls left continuously.
/// </summary>
public sealed class ScrollState
{
    /// <summary>Horizontal scroll offset (decrements as text scrolls left).</summary>
    public int PixelsLeft { get; set; } = 1;

    /// <summary>Vertical scroll offset (increments as text scrolls up into view).</summary>
    public int PixelsUp { get; set; }

    /// <summary>Whether the text has finished scrolling up and is now scrolling horizontally.</summary>
    public int HasElevated { get; set; }

    /// <summary>Frame counter used for pause delays between scroll phases.</summary>
    public int PauseCount { get; set; }

    /// <summary>Resets all scroll state to initial values.</summary>
    public void Reset()
    {
        PixelsLeft = 1;
        PixelsUp = 0;
        HasElevated = 0;
        PauseCount = 0;
    }
}
