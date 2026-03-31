namespace PiDepartures.Models;

/// <summary>
/// Represents a single train departure parsed from the OpenLDBWS SOAP response.
/// </summary>
public sealed class Departure
{
    /// <summary>Scheduled departure time as shown on the timetable (e.g. "14:32").</summary>
    public string AimedDepartureTime { get; set; } = "";

    /// <summary>Expected (live) departure time, or "On time" / "Cancelled" / "Delayed".</summary>
    public string ExpectedDepartureTime { get; set; } = "";

    /// <summary>Final destination station name.</summary>
    public string DestinationName { get; set; } = "";

    /// <summary>Platform number, if known.</summary>
    public string? Platform { get; set; }

    /// <summary>Train operating company name.</summary>
    public string Operator { get; set; } = "";

    /// <summary>Number of carriages, or 0 if unknown.</summary>
    public int Carriages { get; set; }

    /// <summary>Comma-separated list of calling points between origin and destination.</summary>
    public string CallingAtList { get; set; } = "";
}
