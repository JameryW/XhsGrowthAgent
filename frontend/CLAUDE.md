# CLAUDE.md

## Project Overview

Weather Station Dashboard - A full-stack TypeScript application for monitoring real-time weather data from multiple stations. Built with React frontend and Express API backend, using PostgreSQL for data persistence.

## Tech Stack

- **Frontend**: React 18 + TypeScript + Webpack
- **Backend**: Express.js + TypeScript
- **Database**: PostgreSQL 15
- **Package Manager**: pnpm
- **Containerization**: Docker + Docker Compose

## Project Structure

```
weather-station/
├── packages/
│   ├── api/          # Express REST API server
│   ├── client/       # React frontend application
│   ├── core/         # Shared utilities (config, logger, types)
│   └── models/       # Database models and schemas
├── database/         # SQL initialization scripts
├── docker/           # Dockerfiles for services
├── doc/              # Project documentation
└── env/              # Environment configuration files
```

## Development Commands

```bash
# Install dependencies
pnpm install

# Start development servers (both API and client)
pnpm dev

# Build for production
pnpm build

# Run tests
pnpm test

# Lint code
pnpm lint

# Type check
pnpm typecheck

# Start with Docker
docker-compose up -d
```

## Environment Setup

1. Copy environment file: `cp env/.env.development .env`
2. Configure PostgreSQL connection in `.env`
3. Run database initialization: `psql -f database/init.sql`
4. Start development: `pnpm dev`

## API Endpoints

- `GET /api/weather` - Get latest weather data
- `GET /api/weather/history` - Get historical data
- `GET /api/stations` - List all stations
- `POST /api/stations` - Register new station

## Key Components

- **DataCard**: Displays individual weather metrics (temperature, humidity, wind, etc.)
- **Layout**: Main application layout with sidebar navigation
- **Navbar**: Top navigation with station selector
- **WeatherIcon**: SVG weather condition icons
- **useWeather**: Custom hook for fetching and managing weather data

## Database Schema

PostgreSQL tables:
- `stations` - Weather station metadata
- `weather_data` - Time-series weather readings
- `alerts` - Weather alerts and notifications

## Documentation

- `doc/REQUIREMENTS.md` - Functional and non-functional requirements
- `doc/TECH_STACK.md` - Technology choices and rationale
- `doc/DEPLOYMENT.md` - Deployment procedures and configuration
