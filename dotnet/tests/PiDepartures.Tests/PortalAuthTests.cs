using PiDepartures.Config;

namespace PiDepartures.Tests;

public class PortalAuthTests
{
    // ── Password hash round-trip ────────────────────────────────────────

    [Fact]
    public void VerifyPassword_RoundTrip_MatchesOriginal()
    {
        var password = "sup3r-s3cret!";
        var hash = ConfigLoader.HashPassword(password);

        Assert.True(ConfigLoader.VerifyPassword(password, hash));
    }

    [Fact]
    public void VerifyPassword_RoundTrip_RejectsDifferentPassword()
    {
        var hash = ConfigLoader.HashPassword("correct-password");

        Assert.False(ConfigLoader.VerifyPassword("wrong-password", hash));
    }

    [Fact]
    public void VerifyPassword_RoundTrip_WorksWithSpecialCharacters()
    {
        var password = "p@$$w0rd!&*#<>\"'";
        var hash = ConfigLoader.HashPassword(password);

        Assert.True(ConfigLoader.VerifyPassword(password, hash));
    }

    // ── HashPassword format validation ──────────────────────────────────

    [Fact]
    public void HashPassword_Format_HasFiveColonSeparatedParts()
    {
        var hash = ConfigLoader.HashPassword("test");
        var parts = hash.Split(':');

        Assert.Equal(5, parts.Length);
    }

    [Fact]
    public void HashPassword_Format_StartsWithPbkdf2Sha256()
    {
        var hash = ConfigLoader.HashPassword("test");

        Assert.StartsWith("pbkdf2:sha256:", hash);
    }

    [Fact]
    public void HashPassword_Format_ContainsCorrectIterationCount()
    {
        var hash = ConfigLoader.HashPassword("test");
        var parts = hash.Split(':');

        Assert.Equal("260000", parts[2]);
    }

    [Fact]
    public void HashPassword_Format_SaltIsValidHex()
    {
        var hash = ConfigLoader.HashPassword("test");
        var saltHex = hash.Split(':')[3];

        // 16-byte salt = 32 hex characters
        Assert.Equal(32, saltHex.Length);
        Assert.True(saltHex.All(c => "0123456789abcdef".Contains(c)));
    }

    [Fact]
    public void HashPassword_Format_HashIsValidBase64()
    {
        var hash = ConfigLoader.HashPassword("test");
        var hashBase64 = hash.Split(':')[4];

        // Should not throw
        var bytes = Convert.FromBase64String(hashBase64);
        Assert.Equal(32, bytes.Length);
    }

    // ── ValidatePortalConfig catches common errors ──────────────────────

    [Fact]
    public void ValidatePortalConfig_EmptyDict_ReportsApiKeyAndStation()
    {
        var data = new Dictionary<string, string>();
        var errors = ConfigLoader.ValidatePortalConfig(data);

        Assert.True(errors.Count >= 2);
        Assert.Contains(errors, e => e.Contains("API_KEY"));
        Assert.Contains(errors, e => e.Contains("DEPARTURE_STATION"));
    }

    [Fact]
    public void ValidatePortalConfig_WhitespaceApiKey_ReportsError()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "   ",
            ["DEPARTURE_STATION"] = "PAD",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("API_KEY"));
    }

    [Fact]
    public void ValidatePortalConfig_NonNumericRefreshTime_ReportsError()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "key",
            ["DEPARTURE_STATION"] = "PAD",
            ["REFRESH_TIME"] = "abc",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("REFRESH_TIME"));
    }

    [Fact]
    public void ValidatePortalConfig_InvalidBlankHoursFormat_ReportsError()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "key",
            ["DEPARTURE_STATION"] = "PAD",
            ["SCREEN_BLANK_HOURS"] = "1-6",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("SCREEN_BLANK_HOURS"));
    }

    [Fact]
    public void ValidatePortalConfig_InvalidDestinationStation_ReportsError()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "key",
            ["DEPARTURE_STATION"] = "PAD",
            ["DESTINATION_STATION"] = "XX",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("DESTINATION_STATION"));
    }
}
