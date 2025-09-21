# Davis Wind Sensor Plugin - Next Steps

## Completed ✅
- [x] Core plugin implementation with serial communication
- [x] Davis Arduino serial protocol parsing
- [x] Wind speed calculation from RPM measurements
- [x] Wind direction calculation from potentiometer readings
- [x] WXT-style topic naming (env.wind.*) for compatibility
- [x] Davis-specific debug output (RPS, RPM, potentiometer values)
- [x] Command line argument handling
- [x] Docker containerization
- [x] Waggle plugin framework integration
- [x] Comprehensive documentation (README.md)
- [x] Configuration files (sage.yaml, requirements.txt)
- [x] RPM to wind speed calibration support
- [x] Wind direction calibration (offset and scaling)
- [x] Continuous data reading (blocking instead of polling intervals)
- [x] GitHub Actions for automated multi-arch Docker builds
- [x] Automated publishing to GitHub Container Registry
- [x] Code quality testing workflows
- [x] Optional web monitoring interface with real-time dashboard
- [x] Configurable interval averaging for environmental data
- [x] Vector averaging for wind direction (proper circular statistics)
- [x] Wind direction consistency metrics
- [x] Wind speed min/max tracking (lull and gust measurements)
- [x] Tempest weather station calibration integration (UDP-based standalone utility)
- [x] Remove vestigial Tempest web interface code and fix AttributeError issues
- [x] **Full automatic calibration with integrated UDP listening and data collection**
  - Integrated Tempest UDP broadcast listener directly into main.py
  - Automatic Davis + Tempest reading collection and comparison
  - Real-time calibration factor calculation and confidence assessment
  - Automatic application of calibration factors when confidence meets threshold
  - Comprehensive error handling and user guidance
- [x] **Continuous calibration mode for automatic long-term adjustments** 
  - Added continuous calibration mode to entrypoint.sh (DAVIS_MODE=continuous)
  - Standalone continuous calibration in tempest.py (--continuous flag)
  - Background continuous calibration in main.py (--continuous-calibration flag)
  - Automatic 15-minute interval adjustments (configurable)
  - Gradual calibration adjustments (30% per cycle) to prevent sudden jumps
  - Confidence-based calibration application with configurable thresholds
  - Thread-safe operation without disrupting normal sensor data collection
  - Robust error handling with automatic retry logic for long-term deployments
- [x] **Tempest comparison data logging for calibration monitoring**
  - Added side-by-side Davis vs Tempest data logging when averaged data is published
  - Shows current Tempest reading alongside Davis averaged measurements
  - Calculates and displays speed and direction differences between sensors
  - Proper angular distance calculation for wind direction differences
  - Graceful handling when Tempest data is unavailable
- [x] **Comprehensive continuous calibration documentation in README.md**
  - Added detailed continuous calibration mode section with usage examples
  - Documented all configuration options and command line arguments
  - Added Docker deployment examples for continuous mode
  - Included comparison table between auto-calibration and continuous calibration
  - Complete user-facing documentation for the continuous calibration feature
- [x] **Increase serial port timeout to prevent 'no data too quickly' errors**
  - Updated default timeout from 5.0 to 30.0 seconds across all components
  - Fixed main.py argparse default and help text
  - Updated WindSensorReader constructor default timeout
  - Fixed continuous calibration timeout in both main.py and tempest.py
  - Updated README.md documentation to reflect new timeout default
- [x] **Initial calibration confidence for bootstrap functionality**
  - Added --initial-calibration-confidence argument with 0.3 default
  - ContinuousCalibrator tracks first calibration attempt with has_initial_calibration flag
  - Uses lower confidence threshold (30%) for first calibration to establish baseline
  - Auto-calibration fallback: tries initial confidence if main confidence fails
  - Updated documentation with bootstrap examples and sample output
  - Enables easier system startup with imperfect initial conditions
- [x] **Virtual environment setup in development guide**
  - Added comprehensive 'Development Environment Setup' section to DEVELOPMENT.md
  - Step-by-step venv creation, activation, and dependency installation instructions
  - Virtual environment best practices and troubleshooting guidance
  - Updated testing workflow and quick reference to always use venv
  - Prevents externally-managed-environment errors on modern Python installations
  - Establishes proper Python development environment practices
- [x] **Fix critical serial port conflict between main loop and continuous calibration**
  - Removed separate serial connection attempt in continuous calibration
  - Implemented shared data collection system using calibration_data_queue
  - Added thread-safe data sharing methods (add_data_sample, is_collecting_samples)
  - Modified main loop to feed data to continuous calibrator when collecting samples
  - Ensures single serial connection eliminates port access conflicts
- [x] **Improve git workflow documentation for atomic commits**
  - Updated DEVELOPMENT.md Commit Process section with TODO.md workflow guidance
  - Added DO/DON'T examples for atomic commits vs separate TODO commits
  - Enhanced TODO Best Practices with commit workflow guidance
  - Updated File Update Checklist to include TODO.md in commits
  - Establishes clean git history with atomic commits for related changes

## Testing and Validation 🧪
- [ ] Test with actual Davis wind sensor and Arduino hardware
- [ ] Validate Arduino serial output parsing
- [ ] Test RPM to wind speed conversion accuracy
- [ ] Verify potentiometer to wind direction conversion
- [ ] Test calibration factor functionality
- [ ] Validate WXT-style topic publishing
- [ ] Test serial port connection reliability with Arduino
- [ ] Validate Docker deployment on Waggle nodes
- [ ] Test continuous calibration mode functionality
  - [ ] Validate continuous calibration in standalone tempest.py mode
  - [ ] Test background continuous calibration in main.py 
  - [ ] Verify Docker continuous mode (DAVIS_MODE=continuous)
  - [ ] Test configurable intervals and adjustment rates
  - [ ] Validate thread-safe calibration factor updates
  - [ ] Test confidence-based calibration application
  - [ ] Verify graceful handling of Tempest data unavailability
- [ ] Test Tempest comparison data logging functionality
  - [ ] Verify Tempest data is logged alongside Davis averaged data
  - [ ] Validate speed and direction difference calculations
  - [ ] Test behavior when Tempest data is unavailable
  - [ ] Confirm log output format and readability

## Enhancements 🚀

### Davis-Specific Enhancements
- [ ] Support for multiple Davis sensor types and calibrations
- [ ] Automatic detection of Davis sensor model from Arduino
- [ ] Advanced wind gust detection using RPM fluctuations
- [ ] Support for Davis temperature and humidity sensors
- [ ] Calibration wizard for different cup anemometer sizes
- [x] Wind direction offset and scaling calibration
- [ ] Support for Davis wind vane dead zone calibration

### General Enhancements
- [ ] Add support for NMEA wind data format (other sensors)
- [ ] Implement data buffering for network disconnections
- [ ] Add wind gust detection and reporting
- [ ] Support for multiple wind sensors simultaneously
- [ ] Add statistical calculations (average, min, max over time)
- [ ] Implement automatic baud rate detection

## Configuration Options 🔧
- [ ] Add configuration file support (YAML/JSON)
- [ ] Environment variable configuration
- [ ] Auto-discovery of serial ports
- [ ] Configurable data publishing intervals per measurement
- [ ] Custom measurement naming schemes

## Error Handling & Reliability 🛡️
- [ ] Implement exponential backoff for connection retries
- [ ] Add watchdog timer for sensor health monitoring
- [ ] Graceful handling of malformed data
- [ ] Serial port reconnection on device disconnect
- [ ] Data validation and range checking

## Performance & Optimization ⚡
- [ ] Optimize serial read buffer management
- [ ] Implement concurrent data processing
- [ ] Memory usage optimization
- [ ] CPU usage profiling and optimization
- [ ] Benchmarking against different hardware

## Additional Features 🎯
- [x] Web interface for configuration and monitoring
- [x] Real-time data visualization dashboard
- [ ] Historical data export functionality
- [ ] Integration with weather station networks
- [ ] Support for wind sensor calibration procedures
- [ ] Alert system for extreme wind conditions
- [ ] Data logging and export features in web interface
- [ ] Configurable alert thresholds via web interface

## Documentation & Examples 📚
- [ ] Add example sensor configurations
- [ ] Create hardware setup guide
- [ ] Write troubleshooting FAQ
- [ ] Add performance tuning guide
- [ ] Create deployment examples for different environments

## Integration & Compatibility 🔗
- [ ] Test with various wind sensor manufacturers
- [ ] Ensure compatibility with Waggle Edge Stack updates
- [ ] Integration with existing weather monitoring systems
- [ ] Support for different Linux distributions
- [ ] ARM64 and x86-64 architecture testing

## Quality Assurance 🔍
- [ ] Unit test coverage for all functions
- [ ] Integration tests with mock serial devices
- [ ] Code linting and formatting standards
- [ ] Security audit for serial communication
- [ ] Performance regression testing

## Deployment & Operations 🚀
- [x] Automated CI/CD pipeline setup
- [x] Container registry publishing (GitHub Container Registry)
- [x] Multi-architecture image builds (AMD64/ARM64)
- [x] Multi-mode Docker container (main plugin, calibration, testing)
- [x] Flexible entrypoint script with environment variable configuration
- [x] Docker Compose configuration for easy deployment
- [x] Automatic firewall management for UDP calibration in containers
- [ ] Production deployment procedures
- [ ] Monitoring and alerting setup
- [ ] Backup and recovery procedures
- [ ] Kubernetes deployment manifests
- [ ] Helm chart for easy deployment

---

## Priority Order
1. Testing and Validation (immediate)
2. Error Handling & Reliability (high)
3. Configuration Options (medium)
4. Enhancements (ongoing)
5. Additional Features (future)

## Notes
- Focus on real-world testing first before adding new features
- Reliability and error handling are critical for field deployments
- Keep documentation updated as features are added
- Regular testing on target Waggle hardware recommended 