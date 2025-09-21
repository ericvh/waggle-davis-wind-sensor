# Davis Wind Sensor Plugin - Development Guide

This document provides comprehensive instructions for future development work on the Davis Wind Sensor Plugin project.

## 🏗️ Development Environment Setup

### Prerequisites
- Python 3.7 or higher
- Git for version control
- Docker (optional, for container testing)

### 1. Initial Setup

**Clone the repository:**
```bash
git clone <repository-url>
cd waggle-davis
```

**Create virtual environment:**
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
# venv\Scripts\activate
```

**Install dependencies:**
```bash
# With virtual environment activated
pip install -r requirements.txt
```

**Verify installation:**
```bash
# Test that main script loads without errors
python3 main.py --help
python3 tempest.py --help
```

### 2. Working with Virtual Environment

**Always activate before development:**
```bash
# Navigate to project directory
cd /path/to/waggle-davis

# Activate virtual environment
source venv/bin/activate

# Your prompt should show (venv) indicating it's active
(venv) $ python3 main.py --help
```

**Deactivate when finished:**
```bash
# Deactivate virtual environment
deactivate
```

### 3. Managing Dependencies

**Adding new dependencies:**
```bash
# With venv activated
pip install new-package-name

# Update requirements.txt
pip freeze > requirements.txt

# Commit the updated requirements.txt
git add requirements.txt
git commit -m "Add new-package-name dependency"
```

**Updating existing dependencies:**
```bash
# With venv activated
pip install --upgrade package-name

# Update requirements.txt
pip freeze > requirements.txt
```

### 4. Environment Best Practices

**✅ DO:**
- Always use the virtual environment for development
- Keep `requirements.txt` updated when adding dependencies
- Activate the virtual environment before running any Python commands
- Test that the environment works: `python3 main.py --help`

**❌ DON'T:**
- Install packages globally with `--break-system-packages` (development only)
- Run development commands without activating the virtual environment
- Commit the `venv/` directory (it's in `.gitignore`)
- Mix system Python packages with venv packages

### 5. Troubleshooting Environment Issues

**Virtual environment not working:**
```bash
# Remove and recreate venv
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Import errors:**
```bash
# Verify you're in virtual environment
which python3  # Should show path to venv/bin/python3

# Check installed packages
pip list

# Reinstall requirements if needed
pip install -r requirements.txt
```

**System Python conflicts:**
```bash
# Always use virtual environment to avoid:
# - externally-managed-environment errors
# - Package version conflicts
# - System-wide package pollution
```

## 📝 Development Workflow

### 1. Before Starting Work

1. **Check Current Status**
   ```bash
   git status
   git pull origin main
   ```

2. **Review TODO.md**
   - Check current tasks and priorities
   - Identify what needs to be worked on
   - Update task status as you work

3. **Create Feature Branch (if needed)**
   ```bash
   git checkout -b feature/descriptive-name
   ```

### 2. During Development

1. **Test Changes Regularly**
   - Use syntax checking: `python3 -m py_compile filename.py`
   - Test argument parsing with test scripts
   - Validate Docker functionality if applicable

2. **Update Documentation**
   - Update TODO.md to reflect progress
   - Update README.md if functionality changes
   - Add comments to complex code sections

3. **Follow Coding Standards**
   - Use clear, descriptive variable names
   - Add docstrings to functions and classes
   - Keep functions focused and small
   - Handle errors gracefully

## 🔄 Git Workflow

### Commit Standards

#### Commit Message Format
```
Short descriptive title (50 chars max)

Detailed description of what was changed:
- Feature 1: Description of what was added/changed
- Feature 2: Description of implementation details
- Bug Fix: What was broken and how it was fixed

Key capabilities:
- List main features or benefits
- Explain configuration options
- Note any breaking changes

Usage examples:
- Show how to use new features
- Include command line examples
- Note Docker usage if applicable

Additional notes about impact, testing needs, or deployment considerations.
```

#### Example Good Commit Message
```
Add continuous calibration mode for automatic 15-minute interval adjustments

Features added:
- New 'continuous' mode in entrypoint.sh for Docker deployment
- Standalone continuous calibration in tempest.py with --continuous flag
- Background continuous calibration in main.py with --continuous-calibration flag

Key capabilities:
- Automatically compares Davis sensor readings to Tempest weather station data
- Adjusts calibration factors every 15 minutes (configurable)
- Gradual adjustments (30% per cycle) to prevent sudden jumps
- Confidence-based calibration application (minimum 50% confidence)

Usage examples:
- Docker: DAVIS_MODE=continuous
- Standalone: python3 tempest.py --continuous
- Background: python3 main.py --continuous-calibration

This enables automatic sensor drift correction and environmental adaptation
for long-term deployments without manual intervention.
```

### Commit Process

1. **Stage Your Changes AND TODO.md Updates**
   ```bash
   # Make your code changes
   git add filename1.py filename2.sh
   
   # Update TODO.md to reflect completed work
   git add TODO.md
   
   # OR stage all changes together
   git add .
   ```

2. **Commit with Descriptive Message (Include TODO.md in same commit)**
   ```bash
   git commit -m "Your descriptive commit message

   Implementation details:
   - Feature 1: Description of changes
   - Feature 2: Updated TODO.md to mark task completed
   
   This ensures atomic commits where TODO tracking stays synchronized."
   ```

3. **Push Changes**
   ```bash
   git push origin main
   # OR if on feature branch
   git push origin feature/branch-name
   ```

#### ✅ DO: Atomic Commits
```bash
# Good: Include TODO.md update with the actual change
git add main.py TODO.md
git commit -m "Fix serial port conflict and mark TODO completed"
```

#### ❌ DON'T: Separate TODO Commits
```bash
# Avoid: Separate commits for TODO updates create noise
git add main.py
git commit -m "Fix serial port conflict"
git add TODO.md  
git commit -m "Update TODO.md with completion"  # ← Creates commit noise
```

## 📋 TODO Management

### Updating TODO.md

#### When Completing Tasks
1. **Mark as Completed**
   - Change `- [ ]` to `- [x]`
   - Move from pending section to "Completed ✅" section
   - Add implementation details as sub-bullets

2. **Add New Tasks**
   - Add to appropriate section (Testing, Enhancements, etc.)
   - Use descriptive titles
   - Include implementation details as sub-bullets if complex

#### Example TODO Update
```markdown
## Completed ✅
- [x] **Continuous calibration mode for automatic long-term adjustments** 
  - Added continuous calibration mode to entrypoint.sh (DAVIS_MODE=continuous)
  - Standalone continuous calibration in tempest.py (--continuous flag)
  - Background continuous calibration in main.py (--continuous-calibration flag)
  - Automatic 15-minute interval adjustments (configurable)
  - Thread-safe operation without disrupting normal sensor data collection
```

### TODO Best Practices

- **Be Specific**: Instead of "Fix bugs", write "Fix serial timeout handling in main.py"
- **Include Context**: Add implementation details or references
- **Prioritize**: Use the priority sections appropriately
- **Update Regularly**: Keep TODO.md current with each development session
- **Link Related Tasks**: Group related tasks together
- **Commit with Changes**: Always include TODO.md updates in the same commit as the actual work, not as separate commits

## 🧪 Testing Guidelines

### Before Committing

1. **Activate Virtual Environment**
   ```bash
   # Always activate venv first
   source venv/bin/activate
   ```

2. **Syntax Check**
   ```bash
   python3 -m py_compile main.py
   python3 -m py_compile tempest.py
   ```

2. **Argument Parsing Test** (create test script if needed)
   ```python
   # Test new command line arguments
   parser = argparse.ArgumentParser()
   # Add arguments...
   args = parser.parse_args(test_args)
   # Verify parsing works correctly
   ```

3. **Docker Build Test**
   ```bash
   docker build -t test-image .
   ```

### Testing New Features

1. **Create Test Scripts**
   - Create temporary test files for complex features
   - Test argument parsing separately from main functionality
   - Clean up test files after use

2. **Document Test Procedures**
   - Add test cases to TODO.md testing section
   - Include expected behavior
   - Note any special setup requirements

## 🐳 Docker Development

### Building and Testing
```bash
# Build Docker image
docker build -t waggle-davis-test .

# Test different modes
docker run --help waggle-davis-test
DAVIS_MODE=continuous docker run waggle-davis-test --help
DAVIS_MODE=web docker run -p 8080:8080 waggle-davis-test
```

### Container Modes
- `main` - Normal Davis sensor operation
- `calibrate` - Interactive calibration
- `web` - Web interface calibration
- `continuous` - Continuous auto-calibration
- `test` - Connection testing

## 📚 Documentation Updates

### Files to Update

1. **README.md** - For user-facing changes
2. **TODO.md** - For development progress
3. **DEVELOPMENT.md** - For development process changes
4. **Code Comments** - For complex implementation details

### Documentation Standards

- **Clear Examples**: Include working command line examples
- **Complete Information**: Don't assume prior knowledge
- **Current Information**: Remove outdated examples
- **Structured Format**: Use consistent markdown formatting

## 🔧 Configuration Management

### Adding New Arguments

1. **Add to parse_args()** function
2. **Add help text** with defaults and examples
3. **Test argument parsing** with test script
4. **Update documentation** with new options
5. **Add to TODO.md** testing section

### Configuration Best Practices

- **Sensible Defaults**: Choose defaults that work for most users
- **Clear Help Text**: Explain what the option does and when to use it
- **Validation**: Validate argument values where appropriate
- **Backward Compatibility**: Don't break existing functionality

## 🚀 Deployment Considerations

### For Production Changes

1. **Test Thoroughly**: Especially for calibration-related changes
2. **Document Breaking Changes**: Note in commit message and README
3. **Consider Backward Compatibility**: Avoid breaking existing deployments
4. **Update Examples**: Keep usage examples current

### Container Deployment

- Test multi-architecture builds work correctly
- Verify environment variable configuration
- Test network connectivity requirements
- Validate firewall management functionality

## 🐛 Debugging Tips

### Common Issues

1. **Import Errors**: Use `python3 -m py_compile` to check syntax
2. **Argument Parsing**: Create test scripts to verify argument parsing
3. **Serial Communication**: Test with mock data or debug prints
4. **Docker Issues**: Check container logs and network configuration

### Debugging Tools

```bash
# Check Python syntax
python3 -m py_compile filename.py

# Test Docker build
docker build --no-cache -t debug-image .

# Run with debugging
python3 script.py --debug

# Check container logs
docker logs container-name
```

## 📊 Performance Considerations

### Code Quality

- **Error Handling**: Always handle exceptions gracefully
- **Resource Cleanup**: Use context managers for files and connections
- **Thread Safety**: Use locks for shared data structures
- **Memory Usage**: Clean up temporary data structures

### Optimization Guidelines

- **Profile Before Optimizing**: Identify actual bottlenecks
- **Concurrent Operations**: Use threading for I/O-bound operations
- **Efficient Data Structures**: Choose appropriate data types
- **Minimize Dependencies**: Only import what you need

## 🔒 Security Considerations

- **Input Validation**: Validate all user inputs
- **Serial Communication**: Handle malformed data gracefully
- **Network Access**: Minimize exposed ports and services
- **Privilege Management**: Run with minimal required privileges

## 📞 Support and Troubleshooting

### For Future Developers

1. **Check TODO.md** for known issues and planned improvements
2. **Review commit history** for implementation context
3. **Test with minimal setup** before complex deployments
4. **Document new issues** in TODO.md for future reference

### Getting Help

- Check existing documentation first
- Review similar implementations in the codebase
- Test changes incrementally
- Document solutions for future reference

---

## 📝 Quick Reference

### Essential Commands
```bash
# Activate virtual environment (ALWAYS FIRST)
source venv/bin/activate

# Check status and pull latest
git status && git pull origin main

# Test Python syntax
python3 -m py_compile *.py

# Build and test Docker
docker build -t test .

# Commit changes with good message
git add . && git commit -m "Descriptive message with details"

# Push to repository
git push origin main

# Deactivate when finished
deactivate
```

### File Update Checklist
- [ ] Activate virtual environment (`source venv/bin/activate`)
- [ ] Update TODO.md with progress
- [ ] Test syntax with py_compile
- [ ] Update README.md if user-facing changes
- [ ] Stage all changes including TODO.md updates (`git add . `)
- [ ] Commit with descriptive message (include TODO.md in same commit)
- [ ] Push changes to repository

This development guide should be updated as the project evolves and new patterns emerge. 