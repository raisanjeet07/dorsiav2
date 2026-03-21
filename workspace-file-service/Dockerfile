# Build
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download || true
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/workspace-file-service ./cmd/workspace-file-service

# Run
FROM alpine:3.19
RUN apk add --no-cache ca-certificates wget
COPY --from=build /out/workspace-file-service /usr/local/bin/workspace-file-service
ENV WORKSPACE_FILE_HOST=0.0.0.0
ENV WORKSPACE_FILE_PORT=8090
ENV WORKSPACE_FILE_ROOT=/data/workspaces
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/workspace-file-service"]
