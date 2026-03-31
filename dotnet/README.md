# Pi Train Departure Display — .NET Version

.NET 8 rewrite of the Python train departure display. Same hardware, same config format, same web portal — rewritten in C# with ASP.NET Core.

## Architecture

| Component | .NET Equivalent | Python Original |
|---|---|---|
| Entry point | `Program.cs` (Generic Host) | `main.py` |
| API client | `OpenLdbwsClient` (HttpClient + XDocument) | `trains.py` (requests + xmltodict) |
| Config | `ConfigLoader` (KEY=VALUE parser) | `config.py` |
| Display driver | `Ssd1322Spi` (System.Device.Gpio/SPI) | luma.oled |
| Rendering | `DepartureRenderer` (SixLabors.ImageSharp) | PIL/Pillow |
| Web portal | ASP.NET Core Minimal APIs | Flask |
| Background threads | `BackgroundService` (IHostedService) | `threading.Thread` |
| Password hashing | `Rfc2898DeriveBytes` (PBKDF2-SHA256) | `hashlib.pbkdf2_hmac` |

## Prerequisites

- Raspberry Pi Zero 2W, 3B, 3B+, or 4
- SSD1322 256×64 OLED display (7-pin SPI) — same wiring as Python version
- .NET 8 SDK (installed automatically by the installer)
- National Rail OpenLDBWS API key

## Installation

### On the Pi (via Raspberry Pi Connect):

```bash
curl -fsSL https://raw.githubusercontent.com/OktaneZA/PiDepartures/master/dotnet/install-dotnet.sh -o /tmp/install-dotnet.sh
sudo bash /tmp/install-dotnet.sh
```

The installer will:
1. Install .NET 8 SDK
2. Clone the repo and build the project (self-contained publish)
3. Prompt for API key and departure station
4. Write config to `/etc/train-display/config` (same format as Python version)
5. Install and enable the systemd service

After install, start the service:

```bash
sudo systemctl start train-display
```

## Development (Windows/Mac/Linux)

```bash
cd dotnet/src/PiDepartures
# Run in headless mode (no SPI hardware needed)
DEBUG=true DEPARTURE_STATION=PAD API_KEY=your-key dotnet run
```

## Running Tests

```bash
cd dotnet
dotnet test
```

## Building for Pi

```bash
# From the dotnet/ directory
# For Pi Zero 2W (64-bit OS):
dotnet publish src/PiDepartures/PiDepartures.csproj -c Release -r linux-arm64 --self-contained -o publish/

# For Pi Zero W or 32-bit OS:
dotnet publish src/PiDepartures/PiDepartures.csproj -c Release -r linux-arm --self-contained -o publish/
```

## Config Compatibility

The .NET version reads the same `/etc/train-display/config` file as the Python version. You can switch between them without reconfiguring — just change which systemd service is enabled.

## Project Structure

```
dotnet/
├── PiDepartures.sln
├── install-dotnet.sh
├── README.md
├── src/PiDepartures/
│   ├── Program.cs                  — Entry point (Generic Host + Minimal APIs)
│   ├── PiDepartures.csproj
│   ├── Config/
│   │   ├── DisplayConfig.cs        — Runtime config model
│   │   └── ConfigLoader.cs         — KEY=VALUE parser, PBKDF2, validation
│   ├── Hardware/
│   │   ├── ISsd1322.cs             — Display interface
│   │   ├── Ssd1322Spi.cs           — Real SPI driver (GPIO 24=DC, 25=RST)
│   │   └── NullDisplay.cs          — Headless stub for dev machines
│   ├── Models/
│   │   └── Departure.cs            — Departure data model
│   ├── Rendering/
│   │   ├── DepartureRenderer.cs    — Frame rendering with ImageSharp
│   │   └── ScrollState.cs          — Scroll animation state
│   ├── Services/
│   │   ├── SharedState.cs          — Thread-safe shared departure state
│   │   ├── OpenLdbwsClient.cs      — National Rail SOAP client
│   │   ├── FetchService.cs         — Background API polling
│   │   └── RenderService.cs        — Background display rendering
│   ├── Portal/
│   │   ├── PortalAuth.cs           — Auth filter (localhost/Basic Auth)
│   │   └── PortalEndpoints.cs      — Minimal API route mapping
│   ├── wwwroot/
│   │   └── index.html              — Portal web UI
│   └── fonts/                      — Dot-matrix bitmap fonts
└── tests/PiDepartures.Tests/
    ├── PiDepartures.Tests.csproj
    ├── ConfigLoaderTests.cs
    ├── SharedStateTests.cs
    ├── OpenLdbwsClientTests.cs
    └── PortalAuthTests.cs
```
