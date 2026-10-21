# Sandbox for running model-written code against hidden tests: Python, Node (TypeScript) and .NET.
FROM node:24-bookworm-slim AS node

FROM mcr.microsoft.com/dotnet/sdk:10.0
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
# Warm the file-based app toolchain so the first scored run is not a cold start.
RUN mkdir /warm && cd /warm && printf 'System.Console.WriteLine("ok");\n' > w.cs && dotnet run w.cs && rm -rf /warm
WORKDIR /work
