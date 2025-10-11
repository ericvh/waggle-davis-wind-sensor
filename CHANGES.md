# Davis Wind Sensor Plugin - Change Log

This file documents all implementation details and changes to the project.

## 2025-10-11 - Environment Variable Documentation

### Changes
- **Added comprehensive environment variable documentation to README.md**
  - Created new "Environment Variables" section in Configuration chapter
  - Documented all 27 `DAVIS_*` environment variables in organized tables
  - Variables grouped by category: Basic, Calibration, Web Interface, Auto-Calibration, Continuous Calibration, Direction History
  - Included type information, default values, and descriptions for each variable
  
### Documentation Details
- **Basic Configuration**: 5 variables (port, baudrate, timeout, debug, reporting interval)
- **Calibration Settings**: 3 variables (calibration factor, direction offset, direction scale)
- **Web Interface Settings**: 2 variables (web server enable, web port)
- **Auto-Calibration Settings**: 6 variables (enable, samples, interval, timeout, confidence, firewall)
- **Continuous Calibration Settings**: 10 variables (enable, intervals, samples, confidence thresholds, adjustment rates, bootstrap settings)
- **Direction History Settings**: 2 variables (enable, file path)

### Usage Examples Added
- Basic configuration with environment variables
- Docker deployment with environment variables
- Continuous calibration via environment variables
- Docker Compose configuration example
- CLI argument override demonstration

### Technical Implementation
- All environment variables follow the `DAVIS_` prefix convention
- Boolean values support: `true`, `1`, `yes`, `on` (case-insensitive)
- Command-line arguments take precedence over environment variables
- Type conversion handled by `get_env_or_default()` helper function

### Benefits
- Easier Docker deployments with environment-based configuration
- Improved documentation for automated configurations
- Clear reference for all available configuration options
- Better support for container orchestration (Docker Compose, Kubernetes)

### Files Modified
- `README.md` - Added comprehensive environment variable section (~140 lines)
- `TODO.md` - Marked environment variable configuration task as complete

### Related Code
- All environment variable support was previously implemented in `main.py` via the `get_env_or_default()` function and argparse default values
- This change only adds documentation; no code changes were required

