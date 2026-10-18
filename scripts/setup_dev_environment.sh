#!/bin/bash
# Development Environment Setup Script
# Run this on your laptop to set up everything

echo "=========================================="
echo "Complynexpay AML Screening - Dev Setup"
echo "=========================================="

# Check OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "✓ Detected Linux"
    
    # Install PostgreSQL
    echo "Installing PostgreSQL..."
    sudo apt update
    sudo apt install -y postgresql postgresql-contrib
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    
elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "✓ Detected macOS"
    
    # Install PostgreSQL via Homebrew
    echo "Installing PostgreSQL..."
    brew install postgresql
    brew services start postgresql
    
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    echo "✓ Detected Windows"
    echo "Please install PostgreSQL from: https://www.postgresql.org/download/windows/"
    echo "After installation, continue with this script"
    read -p "Press Enter when PostgreSQL is installed..."
fi

# Create development database
echo ""
echo "Creating development database..."

sudo -u postgres psql <<EOF
-- Create database
DROP DATABASE IF EXISTS complynex_dev;
CREATE DATABASE complynex_dev;

-- Create user
DROP USER IF EXISTS complynex_dev;
CREATE USER complynex_dev WITH PASSWORD 'dev_password_123';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE complynex_dev TO complynex_dev;

-- Exit
\q
EOF

echo "✓ Database created: complynex_dev"
echo "✓ User: complynex_dev"
echo "✓ Password: dev_password_123"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."

pip install --upgrade pip

pip install psycopg2-binary==2.9.9
pip install thefuzz[speedup]==0.22.1
pip install python-Levenshtein==0.25.0
pip install jellyfish==1.0.3
pip install pyarabic==0.6.15
pip install requests==2.31.0
pip install beautifulsoup4==4.12.3
pip install lxml==5.1.0
pip install Flask==3.0.0
pip install Flask-Login==0.6.3
pip install Flask-WTF==1.2.1

echo "✓ All dependencies installed"

# Create directory structure
echo ""
echo "Creating project directories..."

mkdir -p screening/
mkdir -p scripts/
mkdir -p data/downloads/
mkdir -p data/backups/
mkdir -p logs/
mkdir -p blueprints/screening/templates/screening/
mkdir -p static/css/

echo "✓ Directories created"

# Create .env file for development
echo ""
echo "Creating .env file..."

cat > .env <<EOF
# Development Environment Configuration
DB_HOST=localhost
DB_NAME=complynex_dev
DB_USER=complynex_dev
DB_PASSWORD=dev_password_123
DB_PORT=5432

FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=dev_secret_key_change_in_production

# Data source update intervals (hours)
OPENSANCTIONS_UPDATE_INTERVAL=24
UN_UPDATE_INTERVAL=24
OFAC_UPDATE_INTERVAL=24
EU_UPDATE_INTERVAL=24
HMT_UPDATE_INTERVAL=24
EMLCU_UPDATE_INTERVAL=168  # Weekly for EMLCU
EOF

echo "✓ .env file created"

echo ""
echo "=========================================="
echo "✅ Development environment setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Run: python scripts/create_database_schema.py"
echo "2. Run: python scripts/scrape_all_sources.py"
echo "3. Run: python scripts/test_screening.py"
echo "4. Start app: flask run"
