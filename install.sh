#!/bin/bash
# YAYS - Yet Another YouTube Summarizer
# ======================================
# Smart installer with auto-detection and systemd service support
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/icon3333/YAYS/main/install.sh | bash
#
# What this does:
# 1. Checks prerequisites (Docker, git)
# 2. Clones or updates the repository to ~/YAYS
# 3. Automatically starts containers
# 4. Offers systemd service installation (if available)
#
# ⚠️ DATABASE SAFETY GUARANTEE:
# This script NEVER modifies or deletes the database (data/videos.db)
# Updates are safe and preserve all your data, channels, and settings

set -e  # Exit on error

# =============================================================================
# Configuration
# =============================================================================

REPO_URL="https://github.com/icon3333/YAYS.git"
PROJECT_NAME="yays"
INSTALL_DIR="$(pwd)/$PROJECT_NAME"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Global variables
IS_UPDATE=false
DOCKER_COMPOSE=""
PORT=""

# =============================================================================
# Utility Functions
# =============================================================================

print_header() {
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_step() {
    echo -e "\n${BLUE}▶${NC} $1"
}

exit_with_error() {
    print_error "$1"
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# =============================================================================
# Docker Compose Detection
# =============================================================================

detect_docker_compose() {
    if docker compose version &>/dev/null; then
        DOCKER_COMPOSE="docker compose"
    elif command_exists docker-compose; then
        DOCKER_COMPOSE="docker-compose"
    else
        exit_with_error "Neither 'docker compose' nor 'docker-compose' found. Please install Docker with Compose support."
    fi
}

# =============================================================================
# Prerequisite Checks
# =============================================================================

check_prerequisites() {
    print_step "Checking prerequisites..."

    # Check Docker
    if ! command_exists docker; then
        exit_with_error "Docker is not installed. Please install Docker first:

        macOS:   brew install --cask docker
        Linux:   curl -fsSL https://get.docker.com | sh

        Visit: https://docs.docker.com/get-docker/"
    fi

    if ! docker ps >/dev/null 2>&1; then
        exit_with_error "Docker daemon is not running. Please start Docker first."
    fi

    print_success "Docker is installed and running"

    # Detect Docker Compose
    detect_docker_compose
    print_success "Docker Compose is available ($DOCKER_COMPOSE)"

    # Check git
    if ! command_exists git; then
        exit_with_error "Git is not installed. Please install git first:

        macOS:   brew install git
        Linux:   sudo apt-get install git  (or yum/dnf on RHEL-based)"
    fi

    print_success "Git is installed"
}

# =============================================================================
# Installation
# =============================================================================

clone_or_update_repository() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        IS_UPDATE=true
        print_step "Existing installation detected - updating..."

        cd "$INSTALL_DIR" || exit_with_error "Failed to enter directory: $INSTALL_DIR"

        # Stop containers if running
        if $DOCKER_COMPOSE ps | grep -q "Up"; then
            print_info "Stopping containers..."
            $DOCKER_COMPOSE down
        fi

        # ⚠️ CRITICAL: Database preservation
        # The data/ directory contains videos.db and MUST be preserved during updates
        # This is safe because:
        # 1. data/ is in .gitignore - git reset won't touch it
        # 2. Docker bind mounts preserve data across container rebuilds
        # DO NOT add any commands that delete or modify data/ directory

        # ⚠️ .env file preservation (optional)
        # The .env file contains configuration settings. It's preserved during updates
        # for convenience, though settings are now stored in the database.
        # YAYS_MASTER_KEY (if present) is only used for one-time migration of old encrypted settings.
        if [ -f ".env" ]; then
            print_info "Backing up .env file..."
            cp .env .env.backup.tmp
        else
            print_warning ".env file not found - will be created from example"
        fi

        print_info "Pulling latest changes from GitHub..."
        git fetch origin
        git reset --hard origin/main

        # Restore .env file after git operations
        if [ -f ".env.backup.tmp" ]; then
            print_info "Restoring .env file..."
            mv .env.backup.tmp .env

            # Create timestamped permanent backup of .env for safety
            TIMESTAMP=$(date +%Y%m%d_%H%M%S)
            cp .env "data/.env.backup.$TIMESTAMP"
            print_success ".env file preserved with your credentials"
            print_info "Permanent backup saved to: data/.env.backup.$TIMESTAMP"
        elif [ -f ".env.example" ] && [ ! -f ".env" ]; then
            # Only create from example if no .env exists and no backup was found
            print_info "Creating .env from example..."
            cp .env.example .env
            print_warning "Please configure credentials in .env or via Web UI Settings"
        fi

        echo ""
        print_info "Updated to:"
        git log --oneline -3
        echo ""

        print_success "Updated to latest version"
    elif [ -d "$INSTALL_DIR" ]; then
        print_warning "Directory $INSTALL_DIR exists but is not a git repo"
        exit_with_error "Please remove or rename $INSTALL_DIR and try again"
    else
        print_step "Installing YAYS..."
        git clone "$REPO_URL" "$INSTALL_DIR" || exit_with_error "Failed to clone repository"
        cd "$INSTALL_DIR" || exit_with_error "Failed to enter directory: $INSTALL_DIR"
        print_success "Repository cloned to $INSTALL_DIR"
    fi
}

# =============================================================================
# Docker Operations
# =============================================================================

start_containers() {
    print_step "Starting containers..."

    # Extract port from docker-compose.yml
    PORT=$(grep -A1 "ports:" docker-compose.yml | grep -o "[0-9]\{4,5\}:8000" | cut -d: -f1 || echo "8015")

    # ⚠️ CRITICAL: Database preservation
    # The mkdir -p command ONLY creates directories if they don't exist
    # It will NEVER delete or modify existing data/videos.db
    # Docker container runs as UID 65532 (nonroot, Chainguard), so we need to ensure these directories are writable
    print_info "Setting up data directories..."
    mkdir -p data logs

    # Set permissions to allow container user (UID 65532) to write
    # 777 is safe here as these are local bind mounts on homeserver
    chmod 777 data logs 2>/dev/null || true

    if [ "$IS_UPDATE" = true ]; then
        # For updates, rebuild with no cache
        print_info "Rebuilding containers (this takes ~60 seconds)..."
        $DOCKER_COMPOSE build --no-cache --pull
    else
        # For fresh installs, normal build
        print_info "Building containers (this takes ~60 seconds)..."
        $DOCKER_COMPOSE build
    fi

    print_info "Starting services..."
    $DOCKER_COMPOSE up -d

    print_info "Waiting for services to be healthy..."
    sleep 5

    print_success "Containers started successfully"
}

# =============================================================================
# Systemd Service Installation
# =============================================================================

offer_systemd_service() {
    # Only offer on Linux systems with systemd
    if [[ "$OSTYPE" != "linux-gnu"* ]] || ! command_exists systemctl; then
        return 0
    fi

    # Check if service file exists
    if [ ! -f "youtube-summarizer.service" ]; then
        return 0
    fi

    # Check if already installed
    if systemctl is-enabled --quiet youtube-summarizer 2>/dev/null; then
        print_info "Systemd service already installed"
        return 0
    fi

    echo ""
    print_step "Systemd service installation available"
    print_info "This will automatically start YAYS on boot"
    echo ""
    read -p "Install systemd service? (y/N): " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        install_systemd_service
    else
        print_info "Skipped systemd service installation"
        print_info "You can install it later by running: ./install-service.sh"
    fi
}

install_systemd_service() {
    USERNAME=$(whoami)
    PROJECT_DIR=$(pwd)

    print_info "Installing systemd service..."

    # Create temporary service file with correct paths
    TEMP_SERVICE=$(mktemp)
    sed "s|YOUR_USERNAME|$USERNAME|g" youtube-summarizer.service > "$TEMP_SERVICE"
    sed "s|WorkingDirectory=/home/$USERNAME/youtube-summarizer|WorkingDirectory=$PROJECT_DIR|g" "$TEMP_SERVICE" > "${TEMP_SERVICE}.tmp"
    mv "${TEMP_SERVICE}.tmp" "$TEMP_SERVICE"

    # Update docker-compose command if using modern syntax
    if [[ "$DOCKER_COMPOSE" == "docker compose" ]]; then
        sed "s|/usr/bin/docker-compose|/usr/bin/docker compose|g" "$TEMP_SERVICE" > "${TEMP_SERVICE}.tmp"
        mv "${TEMP_SERVICE}.tmp" "$TEMP_SERVICE"
    fi

    # Install service file
    sudo cp "$TEMP_SERVICE" /etc/systemd/system/youtube-summarizer.service
    rm "$TEMP_SERVICE"

    # Reload and enable
    sudo systemctl daemon-reload
    sudo systemctl enable youtube-summarizer

    print_success "Systemd service installed and enabled"
    print_info "Service will start automatically on boot"
}

# =============================================================================
# Final Messages
# =============================================================================

print_success_message() {
    echo ""
    print_header "Installation Complete!"

    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}YAYS is now running!${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${YELLOW}Web UI:${NC} http://localhost:$PORT"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "  1. Open the Web UI above"
    echo "  2. Go to Settings tab and configure:"
    echo "     - OpenAI API key"
    echo "     - Target email address"
    echo "     - SMTP credentials (for email delivery)"
    echo "  3. Add YouTube channels in the Channels tab"
    echo "  4. Start processing videos!"
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}Useful Commands:${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  View logs:           $DOCKER_COMPOSE logs -f"
    echo "  Restart:             $DOCKER_COMPOSE restart"
    echo "  Stop:                $DOCKER_COMPOSE stop"
    echo "  Update:              ./update.sh"
    echo "  Process now:         docker exec youtube-summarizer python process_videos.py"
    echo ""
    echo -e "${YELLOW}Documentation:${NC} $INSTALL_DIR/README.md"
    echo ""
}

# =============================================================================
# Main
# =============================================================================

main() {
    print_header "YAYS - Yet Another YouTube Summarizer"

    check_prerequisites
    clone_or_update_repository
    start_containers
    offer_systemd_service
    print_success_message
}

# Run main function
main "$@"
