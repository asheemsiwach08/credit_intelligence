# Credit Intelligence API

A FastAPI-based service for generating credit intelligence reports from PDF files, JSON data, or S3 sources.

## Features

- Generate credit intelligence reports from uploaded PDF/JSON files
- Process data from S3 URLs (s3://bucket/key format)
- Use raw JSON payload strings
- Fallback to stored data using PAN ID
- OpenAI-powered report generation
- Database persistence and S3 file storage

## Quick Start

### Prerequisites

1. Python 3.8+
2. Required environment variables (see Configuration section)
3. Dependencies installed from `requirements.txt`

### Running the API

#### Method 1: Direct Python execution
```bash
python app/main.py
```

#### Method 2: Using uvicorn command
```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

The API will be available at:
- **Main API**: `http://localhost:9000`
- **Interactive Documentation**: `http://localhost:9000/docs`
- **Alternative Documentation**: `http://localhost:9000/redoc`

## API Endpoints

### Health and Monitoring Endpoints

#### GET `/healthz`
Basic liveness probe that checks if the application process is running.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "process_id": 12345,
  "uptime_seconds": 3600.5
}
```

#### GET `/readyz`
Comprehensive readiness probe that checks all dependencies including database, OpenAI API, and AWS S3.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "checks": {
    "database": {
      "status": "healthy",
      "response_time_ms": 45.2,
      "message": "Database connection successful"
    },
    "openai": {
      "status": "healthy",
      "response_time_ms": 120.5,
      "message": "OpenAI API connection successful",
      "models_available": 15
    },
    "aws_s3": {
      "status": "healthy",
      "response_time_ms": 85.3,
      "message": "S3 connection successful",
      "bucket": "your-s3-bucket"
    },
    "system_resources": {
      "status": "healthy",
      "memory_percent": 45.2,
      "disk_percent": 32.1,
      "cpu_percent": 15.8,
      "warnings": [],
      "message": "System resources within normal range"
    }
  }
}
```

#### GET `/info`
Application information including version, git SHA, build time, and environment details.

**Response:**
```json
{
  "app_name": "Credit Intelligence API",
  "version": "1.0.0",
  "git_sha": "abc123def456...",
  "build_time": "2024-01-15T09:00:00.000Z",
  "python_version": "3.12.0",
  "environment": "production",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### GET `/metrics`
Prometheus-formatted metrics for monitoring and observability.

**Response:** Plain text in Prometheus format including:
- HTTP request counts and durations
- System resource usage (CPU, memory, disk)
- Database and external API connection status
- Active connections and other application metrics

### Business Logic Endpoints

#### POST `/ai/generate_credit_report`

Generate a credit intelligence report from various input sources.

**Parameters:**
- `file` (optional): Uploaded PDF or JSON file
- `source_url` (optional): S3 URI (s3://bucket/key) or raw JSON string
- `fallback_id` (optional): 10-digit PAN ID for stored data
- `prompt` (optional): Custom prompt override
- `pdf_password` (optional): Password for encrypted PDFs
- `user_id` (optional): User identifier for file naming

**Important Notes:**
- Provide exactly ONE of: `file`, `source_url`, or `fallback_id`
- For `source_url`, use either:
  - S3 URI format: `s3://bucket-name/path/to/file.pdf`
  - Raw JSON string: `{"key": "value", ...}`

## Configuration

Set the following environment variables:

```bash
# Required
CREDIT_OPENAI_KEY=your_openai_api_key

# Optional - S3 Configuration
ENV_S3_BUCKET=your_s3_bucket_name
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=your_aws_region

# Optional - PostgreSQL Configuration
ENV_POSTGRES_HOST=your_postgres_host
ENV_POSTGRES_PORT=5432
ENV_POSTGRES_USER=postgres
ENV_POSTGRES_PASSWORD=your_password
ENV_POSTGRES_DB=postgres
ENV_POSTGRES_TABLE=credit_intelligence

# Optional - Build Information (for /info endpoint)
BUILD_TIME=2024-01-15T09:00:00.000Z
ENV=production
```

## Monitoring and Observability

The application provides comprehensive health checks and monitoring capabilities:

### Health Checks

- **Liveness Probe** (`/healthz`): Quick check to verify the application is running
- **Readiness Probe** (`/readyz`): Comprehensive check of all dependencies
- **Application Info** (`/info`): Version, build, and environment information

### Metrics

The `/metrics` endpoint provides Prometheus-compatible metrics including:

- **HTTP Metrics**: Request counts, durations, and status codes
- **System Metrics**: CPU, memory, and disk usage
- **Dependency Status**: Database, OpenAI API, and S3 connectivity
- **Application Metrics**: Process information and resource usage

### Kubernetes Integration

These endpoints are designed to work seamlessly with Kubernetes:

```yaml
# Example Kubernetes deployment with health checks
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: credit-intelligence-api
        livenessProbe:
          httpGet:
            path: /healthz
            port: 9000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /readyz
            port: 9000
          initialDelaySeconds: 5
          periodSeconds: 5
```

## Troubleshooting

### Common Issues

1. **API hangs when using source_url**
   - Ensure your `source_url` is either:
     - A valid S3 URI (s3://bucket/key)
     - A valid JSON string
     - A local file path that exists
   - Check the logs for detailed error messages

2. **404 Error on /ai/docs**
   - The documentation is available at `/docs`, not `/ai/docs`
   - Visit `http://localhost:9000/docs` for interactive API docs

3. **Environment Variables Missing**
   - Ensure all required environment variables are set
   - Check that `CREDIT_OPENAI_KEY` is properly configured

### Debug Mode

The API includes comprehensive logging. Check the console output for detailed information about:
- Input parameter processing
- File/S3 loading operations
- OpenAI API calls
- Database operations
- Error details

## Project Structure

```
credit_intelligence/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── api/
│   │   └── router.py          # API route definitions
│   ├── models/
│   │   └── credit_base_model.py
│   ├── prompts/
│   │   └── default_prompt.py
│   ├── services/
│   │   └── credit_intelligence_agent.py
│   ├── utils/
│   │   ├── data_loaders.py
│   │   ├── data_utils.py
│   │   ├── error_handling.py
│   │   └── queries.py
│   └── views/
│       └── credit_intelligence.py
├── Dockerfile
├── Jenkinsfile
├── openapi.yaml
├── README.md
└── requirements.txt
```

## Development

### Running Tests
```bash
# Add test commands here when available
```

### Code Style
```bash
# Add linting commands here when available
```

## License

[Add your license information here]