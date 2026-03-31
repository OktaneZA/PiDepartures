using PiDepartures.Models;
using PiDepartures.Services;

namespace PiDepartures.Tests;

public class SharedStateTests
{
    // ── Initial state ───────────────────────────────────────────────────

    [Fact]
    public void InitialState_DeparturesAreNull()
    {
        var state = new SharedState();
        var (departures, _, _, _) = state.GetSnapshot();

        Assert.Null(departures);
    }

    [Fact]
    public void InitialState_StationNameIsEmpty()
    {
        var state = new SharedState();
        var (_, stationName, _, _) = state.GetSnapshot();

        Assert.Equal("", stationName);
    }

    [Fact]
    public void InitialState_ErrorCountIsZero()
    {
        var state = new SharedState();
        var (_, _, errorCount, _) = state.GetSnapshot();

        Assert.Equal(0, errorCount);
    }

    [Fact]
    public void InitialState_EpochIsZero()
    {
        var state = new SharedState();
        var (_, _, _, epoch) = state.GetSnapshot();

        Assert.Equal(0, epoch);
    }

    // ── Update ──────────────────────────────────────────────────────────

    [Fact]
    public void Update_SetsDeparturesAndStation()
    {
        var state = new SharedState();
        var deps = new List<Departure>
        {
            new() { DestinationName = "Bristol Temple Meads" },
        };

        state.Update(deps, "London Paddington");

        var (departures, stationName, _, _) = state.GetSnapshot();
        Assert.NotNull(departures);
        Assert.Single(departures);
        Assert.Equal("Bristol Temple Meads", departures[0].DestinationName);
        Assert.Equal("London Paddington", stationName);
    }

    [Fact]
    public void Update_ResetsErrorCount()
    {
        var state = new SharedState();
        state.IncrementError();
        state.IncrementError();

        state.Update(null, "Test");

        var (_, _, errorCount, _) = state.GetSnapshot();
        Assert.Equal(0, errorCount);
    }

    [Fact]
    public void Update_IncrementsEpoch()
    {
        var state = new SharedState();
        var (_, _, _, epochBefore) = state.GetSnapshot();

        state.Update(null, "Test");

        var (_, _, _, epochAfter) = state.GetSnapshot();
        Assert.Equal(epochBefore + 1, epochAfter);
    }

    // ── IncrementError ──────────────────────────────────────────────────

    [Fact]
    public void IncrementError_IncrementsCountAndReturnsNewCount()
    {
        var state = new SharedState();

        var count1 = state.IncrementError();
        var count2 = state.IncrementError();

        Assert.Equal(1, count1);
        Assert.Equal(2, count2);
    }

    [Fact]
    public void IncrementError_IncrementsEpoch()
    {
        var state = new SharedState();
        var (_, _, _, epochBefore) = state.GetSnapshot();

        state.IncrementError();

        var (_, _, _, epochAfter) = state.GetSnapshot();
        Assert.Equal(epochBefore + 1, epochAfter);
    }

    // ── GetSnapshot ─────────────────────────────────────────────────────

    [Fact]
    public void GetSnapshot_ReturnsCopyOfList()
    {
        var state = new SharedState();
        var original = new List<Departure>
        {
            new() { DestinationName = "Reading" },
        };

        state.Update(original, "PAD");

        var (snapshot, _, _, _) = state.GetSnapshot();

        Assert.NotNull(snapshot);
        Assert.NotSame(original, snapshot);
        Assert.Equal(original.Count, snapshot.Count);
    }

    // ── RestartRequested ────────────────────────────────────────────────

    [Fact]
    public void RestartRequested_DefaultsFalse()
    {
        var state = new SharedState();
        Assert.False(state.RestartRequested);
    }

    [Fact]
    public void RestartRequested_CanBeSetToTrue()
    {
        var state = new SharedState();
        state.RestartRequested = true;
        Assert.True(state.RestartRequested);
    }
}
