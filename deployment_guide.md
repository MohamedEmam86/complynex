# ComplyNex CMS - Deployment Guide

This guide provides instructions for the IT team to deploy the ComplyNex Full Compliance Platform on internal servers.

## System Requirements
- OS: Linux (Ubuntu 22.04+ recommended) or Windows Server with Docker Desktop
- Software: Docker and Docker Compose
- RAM: 4GB minimum (8GB recommended for large data imports)
- Disk: 10GB free space (database is currently ~1.4GB)

## Deployment Options

### Option 1: Quick Deployment (Using Docker Compose)
This is the recommended "one application" method.
1. Extract the project files on the server.
2. Open a terminal in the project directory.
3. Run the following command:
   ```bash
   docker-compose up -d --build
   ```
4. Access the app at `http://<server-ip>:5000`.

### Option 2: Production Server (Gunicorn)
The Docker image is pre-configured with **Gunicorn**, a production-grade WSGI server.
- Default workers: 4
- Default timeout: 120s

## Database Configuration
The application is currently configured to use **SQLite** (`complynex_cms.db`).

### Migrating to PostgreSQL
If your infrastructure requires PostgreSQL, follow these steps:
1. Update `docker-compose.yml` to include a `db` service.
2. Set the following environment variables in the `web` service:
   - `DB_TYPE=postgresql`
   - `POSTGRES_HOST=db`
   - `POSTGRES_DB=complynex_cms`
   - `POSTGRES_USER=postgres`
   - `POSTGRES_PASSWORD=<your-secure-password>`

## Testing the Deployment
After deployment, verify the following:
1. **Login**: Access the login page and use the default admin credentials (if not already changed).
2. **Data Integrity**: Go to the "Data Sources" page and confirm that total records for "OpenSanctions" show ~800,000+.
3. **Scraping**: Run a test scrape with a limit (e.g., 10 records) to ensure the server can connect to external data sources.

## Support & Troubleshooting
- **Logs**: View application logs using `docker logs complynex_cms`.
- **Database Access**: The SQLite database file is located at `/app/complynex_cms.db` inside the container.
