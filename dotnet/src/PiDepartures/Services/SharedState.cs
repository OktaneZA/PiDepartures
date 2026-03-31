namespace PiDepartures.Services;

using PiDepartures.Models;

/// <summary>
/// Thread-safe shared state between the fetch and render background services.
/// The fetch service writes departure data; the render service reads snapshots.
/// All access is serialized through a lock object.
/// </summary>
public sealed class SharedState
{
    private readonly object _lock = new();
    private List<Departure>? _departures;
    private string _stationName = "";
    private int _errorCount;
    private int _epoch;
    private bool _restartRequested;

    /// <summary>
    /// Returns a consistent snapshot of all shared fields under a single lock acquisition.
    /// </summary>
    /// <returns>
    /// A tuple containing the current departures list (may be null), station name,
    /// consecutive error count, and monotonically increasing epoch counter.
    /// </returns>
    public (List<Departure>? Departures, string StationName, int ErrorCount, int Epoch) GetSnapshot()
    {
        lock (_lock)
        {
            // Return a shallow copy of the list so the caller can iterate without holding the lock.
            var copy = _departures is not null ? new List<Departure>(_departures) : null;
            return (copy, _stationName, _errorCount, _epoch);
        }
    }

    /// <summary>
    /// Replaces the current departure data with a successful fetch result.
    /// Resets the error count to zero and increments the epoch.
    /// </summary>
    /// <param name="departures">Parsed departure list (may be null if no services are running).</param>
    /// <param name="stationName">Display name of the departure station.</param>
    public void Update(List<Departure>? departures, string stationName)
    {
        lock (_lock)
        {
            _departures = departures;
            _stationName = stationName;
            _errorCount = 0;
            _epoch++;
        }
    }

    /// <summary>
    /// Records a fetch failure by incrementing the error count and epoch.
    /// </summary>
    /// <returns>The new error count (1-based), used to calculate backoff delay.</returns>
    public int IncrementError()
    {
        lock (_lock)
        {
            _errorCount++;
            _epoch++;
            return _errorCount;
        }
    }

    /// <summary>
    /// Flag set by the web portal after a configuration save to signal that the
    /// application should restart and reload config. The render service checks
    /// this flag each frame and calls <c>IHostApplicationLifetime.StopApplication()</c>.
    /// </summary>
    public bool RestartRequested
    {
        get
        {
            lock (_lock)
            {
                return _restartRequested;
            }
        }
        set
        {
            lock (_lock)
            {
                _restartRequested = value;
            }
        }
    }
}
