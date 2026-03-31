using PiDepartures.Config;

namespace PiDepartures.Tests;

public class ConfigLoaderTests
{
    // ── LoadRawConfig ───────────────────────────────────────────────────

    [Fact]
    public void LoadRawConfig_ParsesKeyValuePairs()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllText(path, "API_KEY=abc123\nDEPARTURE_STATION=PAD\n");
            var config = ConfigLoader.LoadRawConfig(path);

            Assert.Equal("abc123", config["API_KEY"]);
            Assert.Equal("PAD", config["DEPARTURE_STATION"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void LoadRawConfig_SkipsCommentLines()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllText(path, "# This is a comment\nKEY=value\n");
            var config = ConfigLoader.LoadRawConfig(path);

            Assert.Single(config);
            Assert.Equal("value", config["KEY"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void LoadRawConfig_SkipsBlankLines()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllText(path, "KEY1=a\n\n\nKEY2=b\n");
            var config = ConfigLoader.LoadRawConfig(path);

            Assert.Equal(2, config.Count);
            Assert.Equal("a", config["KEY1"]);
            Assert.Equal("b", config["KEY2"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void LoadRawConfig_StripsDoubleQuotes()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllText(path, "KEY=\"quoted value\"\n");
            var config = ConfigLoader.LoadRawConfig(path);

            Assert.Equal("quoted value", config["KEY"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void LoadRawConfig_StripsSingleQuotes()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllText(path, "KEY='single quoted'\n");
            var config = ConfigLoader.LoadRawConfig(path);

            Assert.Equal("single quoted", config["KEY"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void LoadRawConfig_HandlesEqualsInValue()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllText(path, "KEY=value=with=equals\n");
            var config = ConfigLoader.LoadRawConfig(path);

            Assert.Equal("value=with=equals", config["KEY"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    // ── SaveRawConfig ───────────────────────────────────────────────────

    [Fact]
    public void SaveRawConfig_WritesFile()
    {
        var path = Path.GetTempFileName();
        try
        {
            var data = new Dictionary<string, string>
            {
                ["API_KEY"] = "test123",
                ["DEPARTURE_STATION"] = "PAD",
            };

            ConfigLoader.SaveRawConfig(data, path);

            var roundTripped = ConfigLoader.LoadRawConfig(path);
            Assert.Equal("test123", roundTripped["API_KEY"]);
            Assert.Equal("PAD", roundTripped["DEPARTURE_STATION"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void SaveRawConfig_CanOverwriteExisting()
    {
        var path = Path.GetTempFileName();
        try
        {
            var data1 = new Dictionary<string, string> { ["KEY"] = "first" };
            ConfigLoader.SaveRawConfig(data1, path);

            var data2 = new Dictionary<string, string> { ["KEY"] = "second" };
            ConfigLoader.SaveRawConfig(data2, path);

            var result = ConfigLoader.LoadRawConfig(path);
            Assert.Equal("second", result["KEY"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void SaveRawConfig_QuotesValuesWithSpaces()
    {
        var path = Path.GetTempFileName();
        try
        {
            var data = new Dictionary<string, string> { ["KEY"] = "has spaces" };
            ConfigLoader.SaveRawConfig(data, path);

            // Read back and verify the value survived the round trip
            var result = ConfigLoader.LoadRawConfig(path);
            Assert.Equal("has spaces", result["KEY"]);
        }
        finally
        {
            File.Delete(path);
        }
    }

    // ── HashPassword ────────────────────────────────────────────────────

    [Fact]
    public void HashPassword_ReturnsPbkdf2Format()
    {
        var hash = ConfigLoader.HashPassword("mypassword");

        Assert.StartsWith("pbkdf2:sha256:260000:", hash);
        var parts = hash.Split(':');
        Assert.Equal(5, parts.Length);
    }

    [Fact]
    public void HashPassword_DifferentSaltsEachCall()
    {
        var hash1 = ConfigLoader.HashPassword("password");
        var hash2 = ConfigLoader.HashPassword("password");

        Assert.NotEqual(hash1, hash2);
    }

    // ── VerifyPassword ──────────────────────────────────────────────────

    [Fact]
    public void VerifyPassword_CorrectPasswordReturnsTrue()
    {
        var hash = ConfigLoader.HashPassword("secret");
        Assert.True(ConfigLoader.VerifyPassword("secret", hash));
    }

    [Fact]
    public void VerifyPassword_WrongPasswordReturnsFalse()
    {
        var hash = ConfigLoader.HashPassword("secret");
        Assert.False(ConfigLoader.VerifyPassword("wrong", hash));
    }

    [Fact]
    public void VerifyPassword_HandlesLegacyPlaintext()
    {
        Assert.True(ConfigLoader.VerifyPassword("plaintext", "plaintext"));
        Assert.False(ConfigLoader.VerifyPassword("wrong", "plaintext"));
    }

    [Fact]
    public void VerifyPassword_MalformedHashReturnsFalse()
    {
        Assert.False(ConfigLoader.VerifyPassword("test", "pbkdf2:sha256:badformat"));
    }

    [Fact]
    public void VerifyPassword_EmptyStoredReturnsFalse()
    {
        Assert.False(ConfigLoader.VerifyPassword("test", ""));
    }

    // ── ValidatePortalConfig ────────────────────────────────────────────

    [Fact]
    public void ValidatePortalConfig_MissingApiKeyErrors()
    {
        var data = new Dictionary<string, string>
        {
            ["DEPARTURE_STATION"] = "PAD",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("API_KEY"));
    }

    [Fact]
    public void ValidatePortalConfig_MissingDepartureStationErrors()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "some-key",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("DEPARTURE_STATION"));
    }

    [Fact]
    public void ValidatePortalConfig_InvalidCrsFormatErrors()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "some-key",
            ["DEPARTURE_STATION"] = "TOOLONG",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("CRS"));
    }

    [Fact]
    public void ValidatePortalConfig_ValidConfigReturnsEmptyList()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "some-key",
            ["DEPARTURE_STATION"] = "PAD",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Empty(errors);
    }

    [Fact]
    public void ValidatePortalConfig_InvalidRefreshTimeErrors()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "key",
            ["DEPARTURE_STATION"] = "PAD",
            ["REFRESH_TIME"] = "5",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("REFRESH_TIME"));
    }

    [Fact]
    public void ValidatePortalConfig_InvalidScreenRotationErrors()
    {
        var data = new Dictionary<string, string>
        {
            ["API_KEY"] = "key",
            ["DEPARTURE_STATION"] = "PAD",
            ["SCREEN_ROTATION"] = "9",
        };

        var errors = ConfigLoader.ValidatePortalConfig(data);
        Assert.Contains(errors, e => e.Contains("SCREEN_ROTATION"));
    }
}
