# AI-Powered Travel Itinerary Generator 🌍✈️

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.0%2B-green)](https://flask.palletsprojects.com)
[![MongoDB](https://img.shields.io/badge/MongoDB-5.0%2B-brightgreen)](https://mongodb.com)

An intelligent travel planning system that creates optimized itineraries using AI and real-time data from multiple APIs.

## 🔑 Key Features
- **AI-Powered Suggestions**: GPT-3.5/4 integration for smart recommendations
- **Multi-Day Planning**: Automatic time slot allocation for activities
- **Real-Time Data**:
  - Google Places API integration
  - OpenWeatherMap forecasts
  - Wikipedia city information
- **User Authentication**: Secure login/signup with password hashing
- **Version Control**: Track itinerary modifications over time
- **Responsive UI**: Mobile-friendly web interface

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- MongoDB Atlas account
- API keys for:
  - Google Cloud Platform
  - OpenWeatherMap
  - OpenAI

### Installation
```bash
# Clone repository
git clone https://github.com/yourusername/ai-travel-planner.git
cd ai-travel-planner

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
