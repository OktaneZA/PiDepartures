using System.Text;
using PiDepartures.Config;

namespace PiDepartures.Portal;

/// <summary>
/// ASP.NET Core endpoint filter that enforces portal access control.
/// <list type="bullet">
///   <item>When no <c>PORTAL_PASSWORD</c> is configured, only localhost connections are permitted.</item>
///   <item>When a password is configured, HTTP Basic Authentication is required (username "admin").</item>
/// </list>
/// </summary>
public sealed class PortalAuthFilter : IEndpointFilter
{
    /// <inheritdoc />
    public async ValueTask<object?> InvokeAsync(
        EndpointFilterInvocationContext context,
        EndpointFilterDelegate next)
    {
        var httpContext = context.HttpContext;

        string portalPassword;
        try
        {
            portalPassword = ConfigLoader.LoadRawConfig()
                .GetValueOrDefault("PORTAL_PASSWORD", "");
        }
        catch
        {
            portalPassword = "";
        }

        if (string.IsNullOrEmpty(portalPassword))
        {
            // No password configured — restrict to localhost only.
            var remoteIp = httpContext.Connection.RemoteIpAddress?.ToString();
            if (remoteIp is not ("127.0.0.1" or "::1"))
            {
                return Results.Text(
                    "Remote access requires a portal password.",
                    statusCode: 403);
            }

            return await next(context);
        }

        // Password is configured — require HTTP Basic Auth.
        var authHeader = httpContext.Request.Headers.Authorization.ToString();
        if (!authHeader.StartsWith("Basic ", StringComparison.OrdinalIgnoreCase))
        {
            httpContext.Response.Headers["WWW-Authenticate"] = "Basic realm=\"TrainDisplay\"";
            return Results.Text("Authentication required", statusCode: 401);
        }

        string decoded;
        try
        {
            decoded = Encoding.UTF8.GetString(
                Convert.FromBase64String(authHeader[6..]));
        }
        catch (FormatException)
        {
            httpContext.Response.Headers["WWW-Authenticate"] = "Basic realm=\"TrainDisplay\"";
            return Results.Text("Authentication required", statusCode: 401);
        }

        var parts = decoded.Split(':', 2);
        if (parts.Length != 2
            || parts[0] != "admin"
            || !ConfigLoader.VerifyPassword(parts[1], portalPassword))
        {
            httpContext.Response.Headers["WWW-Authenticate"] = "Basic realm=\"TrainDisplay\"";
            return Results.Text("Authentication required", statusCode: 401);
        }

        return await next(context);
    }
}
