        // Global state
        let channels = [];
        let channelNames = {};
        let channelStats = {};
        let isLoading = false;
        let isLoadingSettings = false;  // Track when programmatically loading settings to prevent false "unsaved" indicators
        let pendingRemoval = null;
        let pendingAction = null;  // For storing the action to be confirmed
        let feedOffset = 0;
        let feedLimit = 25;

        // yt-dlp timing configuration for countdown timers
        let ytdlpTiming = {
            estimated_channel_fetch: 5,
            estimated_video_fetch: 8,
            estimated_metadata_fetch: 3
        };

        // Active countdown timer intervals
        let activeCountdownTimers = [];

        // Video countdown tracking (for status labels)
        let videoCountdowns = {}; // { videoId: { remaining: seconds, interval: intervalId, baseLabel: string } }

        // ============================================================================
        // SETTINGS MANAGEMENT - Centralized Configuration
        // ============================================================================

        /**
         * Centralized configuration for settings sections and their unsaved indicators
         * Single source of truth for section-to-indicator mappings
         */
        const SETTINGS_CONFIG = {
            sections: {
                'email': {
                    indicatorId: 'unsaved-email',
                    saveFunction: 'saveAllSettings'
                },
                'video': {
                    indicatorId: 'unsaved-video',
                    saveFunction: 'saveAllSettings'
                },
                'transcript': {
                    indicatorId: 'unsaved-transcript',
                    saveFunction: 'saveAllSettings'
                },
                'ai-credentials': {
                    indicatorId: 'unsaved-ai-credentials',
                    saveFunction: 'saveAICredentials'
                },
                'prompt': {
                    indicatorId: 'unsaved-prompt',
                    saveFunction: 'savePrompt'
                }
            }
        };

        /**
         * Show unsaved indicator for a settings section
         * Respects isLoadingSettings flag to prevent false positives during programmatic loads
         * @param {string} section - The section name (e.g., 'email', 'video')
         */
        function showUnsavedIndicator(section) {
            // Don't show unsaved indicator if we're programmatically loading settings
            if (isLoadingSettings) {
                return;
            }

            const config = SETTINGS_CONFIG.sections[section];
            if (!config) {
                console.warn(`Unknown settings section: ${section}`);
                return;
            }

            const indicator = document.getElementById(config.indicatorId);
            if (indicator) {
                indicator.style.display = 'inline';
            }
        }

        /**
         * Hide unsaved indicator for a settings section
         * @param {string} section - The section name (e.g., 'email', 'video')
         */
        function hideUnsavedIndicator(section) {
            const config = SETTINGS_CONFIG.sections[section];
            if (!config) {
                console.warn(`Unknown settings section: ${section}`);
                return;
            }

            const indicator = document.getElementById(config.indicatorId);
            if (indicator) {
                indicator.style.display = 'none';
            }
        }

        /**
         * Hide unsaved indicators for multiple sections
         * @param {string[]} sections - Array of section names
         */
        function hideUnsavedIndicators(sections) {
            sections.forEach(section => hideUnsavedIndicator(section));
        }

        /**
         * Hide all unsaved indicators across all settings sections
         */
        function hideAllUnsavedIndicators() {
            Object.keys(SETTINGS_CONFIG.sections).forEach(section => {
                hideUnsavedIndicator(section);
            });
        }

        /**
         * Validate settings configuration on startup
         * Checks that all data-section attributes have corresponding config
         * and that all indicator elements exist in the DOM
         */
        function validateSettingsConfig() {
            const trackableInputs = document.querySelectorAll('.trackable-input');
            const missingSections = new Set();

            // Check for inputs with unknown sections
            trackableInputs.forEach(input => {
                const section = input.getAttribute('data-section');
                if (section && !SETTINGS_CONFIG.sections[section]) {
                    missingSections.add(section);
                }
            });

            if (missingSections.size > 0) {
                console.error('Settings config missing for sections:', Array.from(missingSections));
            }

            // Check for missing indicator elements
            Object.entries(SETTINGS_CONFIG.sections).forEach(([section, config]) => {
                const indicator = document.getElementById(config.indicatorId);
                if (!indicator) {
                    console.error(`Missing indicator element: ${config.indicatorId} for section: ${section}`);
                }
            });
        }

        // ============================================================================
        // YTDLP TIMING
        // ============================================================================

        // Load yt-dlp timing configuration on startup
        async function loadYTDLPTiming() {
            try {
                const response = await fetch('/api/ytdlp/timing');
                if (response.ok) {
                    ytdlpTiming = await response.json();
                    console.log('Loaded yt-dlp timing:', ytdlpTiming);
                }
            } catch (error) {
                console.warn('Failed to load yt-dlp timing, using defaults:', error);
            }
        }

        /**
         * Start a countdown timer on a button element
         * @param {HTMLElement} button - The button element to update
         * @param {string} baseText - The base text to show (e.g., "Resolving")
         * @param {number} seconds - Total seconds to count down
         * @param {boolean} showCountdown - Whether to show the countdown (default: true)
         * @returns {number} - The interval ID
         */
        function startButtonCountdown(button, baseText, seconds, showCountdown = true) {
            // Clear any existing timer for this button
            if (button._countdownInterval) {
                clearInterval(button._countdownInterval);
            }

            if (!showCountdown || seconds <= 0) {
                button.textContent = `${baseText}...`;
                return null;
            }

            let remaining = Math.ceil(seconds);

            // Update immediately
            button.textContent = `${baseText}... (${remaining}s)`;

            // Update every second
            const interval = setInterval(() => {
                remaining--;
                if (remaining > 0) {
                    button.textContent = `${baseText}... (${remaining}s)`;
                } else {
                    button.textContent = `${baseText}...`;
                    clearInterval(interval);
                    button._countdownInterval = null;
                }
            }, 1000);

            // Store interval ID on button for cleanup
            button._countdownInterval = interval;
            activeCountdownTimers.push(interval);

            return interval;
        }

        /**
         * Clear countdown timer for a specific button
         * @param {HTMLElement} button - The button element
         */
        function clearButtonCountdown(button) {
            if (button._countdownInterval) {
                clearInterval(button._countdownInterval);
                button._countdownInterval = null;
            }
        }

        /**
         * Clear all active countdown timers
         */
        function clearAllCountdownTimers() {
            activeCountdownTimers.forEach(interval => clearInterval(interval));
            activeCountdownTimers = [];
        }

        /**
         * Update countdown for a video status label
         * @param {string} videoId - Video ID
         * @param {number} seconds - Countdown in seconds
         */
        function updateVideoCountdown(videoId, seconds) {
            // Clear existing countdown for this video
            if (videoCountdowns[videoId] && videoCountdowns[videoId].interval) {
                clearInterval(videoCountdowns[videoId].interval);
            }

            // Get the status label element
            const statusLabel = document.querySelector(`#video-${videoId} .label-status`);
            if (!statusLabel) return;

            // Store the base label text (without countdown)
            const baseLabel = statusLabel.textContent.replace(/\s*\(\d+s\)$/, '');

            // Update the countdown display
            videoCountdowns[videoId] = {
                remaining: seconds,
                baseLabel: baseLabel,
                interval: setInterval(() => {
                    const countdown = videoCountdowns[videoId];
                    if (!countdown || countdown.remaining <= 0) {
                        // Countdown finished - remove it
                        if (videoCountdowns[videoId]) {
                            clearInterval(videoCountdowns[videoId].interval);
                            delete videoCountdowns[videoId];
                        }
                        if (statusLabel) {
                            statusLabel.textContent = baseLabel;
                        }
                        return;
                    }

                    // Update label with countdown
                    countdown.remaining--;
                    if (statusLabel) {
                        statusLabel.textContent = `${baseLabel} (${countdown.remaining}s)`;
                    }
                }, 1000)
            };

            // Set initial text
            statusLabel.textContent = `${baseLabel} (${seconds}s)`;
        }

        // Load channels
        async function loadChannels() {
            try {
                // Load channels
                const response = await fetch('/api/channels');
                if (!response.ok) throw new Error('Failed to load');

                const data = await response.json();
                channels = data.channels || [];
                channelNames = data.names || {};

                // Load stats
                await loadChannelStats();

                renderChannels();

                // Load video feed
                await loadVideoFeed(true);

                // Populate channel filter
                populateChannelFilter();

            } catch (error) {
                showStatus('Failed to load channels', true);
            } finally {
                document.getElementById('loading').style.display = 'none';
            }
        }

        // Load channel statistics
        async function loadChannelStats() {
            try {
                const response = await fetch('/api/stats/channels');
                if (!response.ok) return;

                const data = await response.json();
                channelStats = data.channels || {};

            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }

        // Render channels with enhanced cards
        function renderChannels() {
            const container = document.getElementById('channels');
            const empty = document.getElementById('empty');
            const count = document.getElementById('count');

            count.textContent = channels.length;

            if (channels.length === 0) {
                empty.style.display = 'block';
                container.innerHTML = '';
                // Regenerate TOC after rendering
                setTimeout(() => generateTOC(), 50);
                return;
            }

            empty.style.display = 'none';
            container.innerHTML = '';

            channels.forEach(id => {
                const name = channelNames[id] || id;
                const showId = name !== id;
                const stats = channelStats[id] || { total_videos: 0, hours_saved: 0 };

                const div = document.createElement('div');
                div.className = 'channel-card';
                div.innerHTML = `
                    <div class="channel-card-header">
                        <div class="channel-name-section">
                            <div class="channel-name">${escapeHtml(name)}</div>
                            ${showId ? `<div class="channel-id">${escapeHtml(id)}</div>` : ''}
                        </div>
                        <div class="channel-stats">
                            <span class="channel-stat">
                                <i class="iconoir-stats-report stat-icon"></i>
                                <span class="stat-value">${stats.total_videos || 0}</span>
                                <span class="stat-label">summaries</span>
                            </span>
                            <span class="stat-separator">•</span>
                            <span class="channel-stat">
                                <i class="iconoir-timer stat-icon"></i>
                                <span class="stat-value">${stats.hours_saved || 0}</span>
                                <span class="stat-label">total hours</span>
                            </span>
                        </div>
                    </div>

                    <div class="channel-actions">
                        <button class="btn-secondary" onclick="viewChannelFeed('${escapeAttr(id)}')">
                            View Feed
                        </button>
                        <button class="btn-remove" onclick="promptRemove('${escapeAttr(id)}')">
                            Remove
                        </button>
                    </div>
                `;
                container.appendChild(div);
            });

            // Regenerate TOC after rendering
            setTimeout(() => generateTOC(), 50);
        }

        // HTML escape
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Attribute escape
        function escapeAttr(text) {
            return text.replace(/'/g, "\\\\'").replace(/"/g, '&quot;');
        }

        // Prompt removal
        function promptRemove(id) {
            pendingRemoval = id;
            const name = channelNames[id] || id;
            document.getElementById('modalMessage').textContent =
                `Are you sure you want to remove "${name}"?`;
            document.getElementById('modal').classList.add('show');
        }

        // Close modal
        function closeModal() {
            document.getElementById('modal').classList.remove('show');
            pendingRemoval = null;
            pendingAction = null;
        }

        // Confirm removal
        async function confirmRemove() {
            if (!pendingRemoval) return;

            const removedChannelId = pendingRemoval;

            channels = channels.filter(id => id !== pendingRemoval);
            delete channelNames[pendingRemoval];

            closeModal();
            await saveChannels();
            renderChannels();

            // Update channel filter dropdown
            populateChannelFilter();

            // If the removed channel was being viewed in feed, clear filter and reload
            const currentFilter = document.getElementById('feedChannelFilter').value;
            if (currentFilter === removedChannelId) {
                document.getElementById('feedChannelFilter').value = '';
                await loadVideoFeed(true);
            }
        }



        // Generic modal prompt
        function showConfirmModal(title, message, confirmText, confirmCallback) {
            document.getElementById('modalTitle').textContent = title;
            document.getElementById('modalMessage').textContent = message;
            document.getElementById('modalConfirmBtn').textContent = confirmText;
            pendingAction = confirmCallback;

            // Update the confirm button onclick
            const confirmBtn = document.getElementById('modalConfirmBtn');
            confirmBtn.onclick = async function() {
                if (pendingAction) {
                    await pendingAction();
                    closeModal();
                }
            };

            document.getElementById('modal').classList.add('show');
        }

        // Risky deletion functions
        async function promptResetSettings() {
            showConfirmModal(
                '⚠️ Reset Settings',
                'This will reset all settings and AI prompt to defaults. Your channels and feed history will be preserved. This action cannot be undone. Are you sure?',
                'Reset Settings',
                confirmResetSettings
            );
        }

        async function confirmResetSettings() {
            try {
                const response = await fetch('/api/reset/settings', {
                    method: 'POST'
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to reset settings');
                }

                const result = await response.json();

                // Show success message
                showSettingsStatus(result.message);

                // Reload the page to reflect changes
                setTimeout(() => location.reload(), 1500);
            } catch (error) {
                showSettingsStatus('Failed to reset settings: ' + error.message, true);
            }
        }

        async function promptResetYoutubeData() {
            showConfirmModal(
                '⚠️ Reset YouTube Data',
                'This will permanently delete all channels and feed history. Your settings and AI prompt will be preserved. This action cannot be undone. Are you sure?',
                'Reset YouTube Data',
                confirmResetYoutubeData
            );
        }

        async function confirmResetYoutubeData() {
            try {
                const response = await fetch('/api/reset/youtube-data', {
                    method: 'POST'
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to reset YouTube data');
                }

                const result = await response.json();

                // Show success message
                showSettingsStatus(result.message);

                // Reload the page to reflect changes
                setTimeout(() => location.reload(), 1500);
            } catch (error) {
                showSettingsStatus('Failed to reset YouTube data: ' + error.message, true);
            }
        }

        async function promptResetFeedHistory() {
            showConfirmModal(
                '⚠️ Reset Feed History',
                'This will permanently delete all processed videos from your feed. Your channels and settings will be preserved. This action cannot be undone. Are you sure?',
                'Reset Feed History',
                confirmResetFeedHistory
            );
        }

        async function confirmResetFeedHistory() {
            try {
                const response = await fetch('/api/reset/feed-history', {
                    method: 'POST'
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to reset feed history');
                }

                const result = await response.json();

                // Show success message
                showSettingsStatus(result.message);

                // Reload the feed
                feedOffset = 0;
                await loadVideoFeed(true);
            } catch (error) {
                showSettingsStatus('Failed to reset feed history: ' + error.message, true);
            }
        }

        async function promptResetCompleteApp() {
            showConfirmModal(
                '⚠️ Reset Complete App',
                'This will permanently delete ALL data including channels, feed history, and reset all settings and prompts to defaults. This action cannot be undone. Are you absolutely sure?',
                'Reset Everything',
                confirmResetCompleteApp
            );
        }

        async function confirmResetCompleteApp() {
            try {
                const response = await fetch('/api/reset/complete', {
                    method: 'POST'
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to reset app');
                }

                const result = await response.json();

                // Show success message
                showSettingsStatus(result.message);

                // Reload the page to reflect changes
                setTimeout(() => location.reload(), 1500);
            } catch (error) {
                showSettingsStatus('Failed to reset app: ' + error.message, true);
            }
        }

        // Toggle Danger Zone visibility
        function toggleDangerZone() {
            const content = document.getElementById('dangerZoneContent');
            const toggle = document.getElementById('dangerZoneToggle');

            if (content.style.display === 'none') {
                content.style.display = 'block';
                toggle.textContent = '▼';
            } else {
                content.style.display = 'none';
                toggle.textContent = '▶';
            }
        }

        // Add channel
        async function addChannel() {
            if (isLoading) return;

            const idInput = document.getElementById('channelId');
            const nameInput = document.getElementById('channelName');
            const addBtn = document.getElementById('addBtn');

            const input = idInput.value.trim();
            let name = nameInput.value.trim();

            if (!input) {
                showStatus('Please enter a channel ID or URL', true);
                return;
            }

            isLoading = true;
            addBtn.disabled = true;
            addBtn.textContent = 'Adding...';

            let channelId;
            let channelName;

            // Check if we have cached channel info from the auto-fetch
            if (cachedChannelInfo && cachedChannelInfo.input === input) {
                // Use cached data - no need to fetch again!
                channelId = cachedChannelInfo.channel_id;
                channelName = name || cachedChannelInfo.channel_name;
                console.log('Using cached channel info (instant!)');
            } else {
                // No cache available, need to fetch
                // This happens if user manually types a channel ID without triggering auto-fetch
                try {
                    const response = await fetch(`/api/fetch-channel-name/${encodeURIComponent(input)}`);

                    if (!response.ok) {
                        const error = await response.json();
                        showStatus(error.detail || 'Invalid channel', true);
                        isLoading = false;
                        addBtn.disabled = false;
                        addBtn.textContent = 'Add Channel';
                        return;
                    }

                    const data = await response.json();
                    channelId = data.channel_id;
                    channelName = name || data.channel_name;

                    if (!name) {
                        nameInput.value = data.channel_name; // Auto-fill
                    }

                } catch (error) {
                    showStatus('Failed to resolve channel: ' + error.message, true);
                    isLoading = false;
                    addBtn.disabled = false;
                    addBtn.textContent = 'Add Channel';
                    return;
                }
            }

            // Check if already exists
            if (channels.includes(channelId)) {
                showStatus('Channel already exists', true);
                isLoading = false;
                addBtn.disabled = false;
                addBtn.textContent = 'Add Channel';
                return;
            }

            // Add to local arrays
            channels.push(channelId);
            channelNames[channelId] = channelName;

            // Save to backend
            const saved = await saveChannels();

            if (saved) {
                // Trigger background video processing (non-blocking)
                try {
                    await fetch('/api/videos/process-now', { method: 'POST' });
                } catch (error) {
                    console.log('Background processing trigger failed (non-critical):', error);
                }

                showStatus(`✓ Channel "${channelName}" added! Videos will be processed in the background.`, false);
            }

            // Clear inputs and refresh UI
            idInput.value = '';
            nameInput.value = '';
            renderChannels();

            isLoading = false;
            addBtn.disabled = false;
            addBtn.textContent = 'Add Channel';
        }

        // Save channels
        async function saveChannels() {
            try {
                const response = await fetch('/api/channels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ channels, names: channelNames })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    console.error('Save failed:', response.status, errorData);
                    throw new Error(`Save failed: ${response.status}`);
                }

                const result = await response.json();
                console.log('Save successful:', result);
                showStatus('Saved successfully', false);
                return true;
            } catch (error) {
                console.error('Save error:', error);
                showStatus('Failed to save: ' + error.message, true);
                return false;
            }
        }

        // Show status message in global status bar
        function showStatus(message, isError) {
            const status = document.getElementById('status');
            if (!status) {
                console.error('Global status element not found');
                return;
            }
            status.textContent = message;
            status.className = isError ? 'status error show' : 'status show';
            setTimeout(() => status.classList.remove('show'), 3000);
        }

        // ============================================================================
        // SAVE CONFIRMATION HELPER
        // ============================================================================

        /**
         * Show save confirmation in a button
         * Temporarily changes button text to show "✓ Saved!" and restores it after delay
         *
         * @param {HTMLElement} button - The button element to update
         * @param {string} confirmText - Text to show on success (default: "✓ Saved!")
         * @param {number} duration - How long to show confirmation in ms (default: 2000)
         */
        function showButtonConfirmation(button, confirmText = '✓ Saved!', duration = 2000) {
            if (!button) return;

            // Store original state
            const originalText = button.textContent;
            const wasDisabled = button.disabled;

            // Show confirmation
            button.textContent = confirmText;
            button.disabled = true;
            button.style.backgroundColor = '#16a34a'; // Green background

            // Restore original state after duration
            setTimeout(() => {
                button.textContent = originalText;
                button.disabled = wasDisabled;
                button.style.backgroundColor = ''; // Reset to default
            }, duration);
        }

        // Video feed functions
        let feedRefreshInterval = null;

        // Logs modal auto-refresh
        let logsRefreshInterval = null;
        let currentLogsVideoId = null;

        /**
         * Load/render the video feed
         * @param {boolean} reset - when true, resets offset and clears list
         * @param {boolean} preserveScroll - when true, restores window scroll after render
         */
        async function loadVideoFeed(reset = false, preserveScroll = false) {
            const savedScrollY = preserveScroll ? window.scrollY : null;
            if (reset) {
                const feedEl = document.getElementById('videoFeed');
                feedOffset = 0;
                // Clear existing items
                feedEl.innerHTML = '';
            }

            try {
                const channelFilter = document.getElementById('feedChannelFilter').value;
                const sortOrder = document.getElementById('feedSortOrder').value;

                const params = new URLSearchParams({
                    limit: feedLimit,
                    offset: feedOffset,
                    order_by: sortOrder
                });

                if (channelFilter === 'manual') {
                    params.append('source_type', 'via_manual');
                } else if (channelFilter) {
                    params.append('channel_id', channelFilter);
                }

                const response = await fetch(`/api/videos/feed?${params}`);
                if (!response.ok) return;

                const data = await response.json();

                // Update count
                document.getElementById('feedCount').textContent = data.total;

                // Show/hide empty state
                if (data.total === 0) {
                    document.getElementById('feedEmpty').style.display = 'block';
                    document.getElementById('videoFeed').style.display = 'none';
                    document.getElementById('loadMoreBtn').style.display = 'none';
                    return;
                } else {
                    document.getElementById('feedEmpty').style.display = 'none';
                    document.getElementById('videoFeed').style.display = 'block';
                }

                // Check if any videos are processing
                const hasProcessingVideos = data.videos.some(v =>
                    v.processing_status === 'processing' ||
                    v.processing_status === 'pending' ||
                    v.processing_status === 'fetching_metadata' ||
                    v.processing_status === 'fetching_transcript' ||
                    v.processing_status === 'generating_summary' ||
                    v.processing_status === 'sending_email'
                );

                // Start auto-refresh if videos are processing, stop otherwise
                if (hasProcessingVideos && !feedRefreshInterval) {
                    console.log('Starting auto-refresh (videos processing)');
                    feedRefreshInterval = setInterval(autoRefreshFeedTick, 5000); // Refresh every 5 seconds
                } else if (!hasProcessingVideos && feedRefreshInterval) {
                    console.log('Stopping auto-refresh (no videos processing)');
                    clearInterval(feedRefreshInterval);
                    feedRefreshInterval = null;
                }

                // Render videos
                const feedContainer = document.getElementById('videoFeed');
                data.videos.forEach(video => {
                    const div = document.createElement('div');
                    div.className = 'video-item';
                    // Tag node for targeted updates later
                    div.id = `video-${video.id}`;
                    div.dataset.videoId = video.id;

                    // Build footer to show source type (manual or channel) and transcript source
                    const isManual = video.source_type === 'via_manual';
                    const sourceInfoText = isManual ? 'manual' : 'channel';

                    // Add transcript source if available
                    let fullSourceText = sourceInfoText;
                    if (video.transcript_source) {
                        fullSourceText += ` • ${video.transcript_source}`;
                    }

                    div.innerHTML = `
                        <div class="video-grid" id="video-actions-${video.id}" data-status="${video.processing_status || ''}" data-retry-count="${video.retry_count || 0}">
                            <div class="video-title" onclick="openYouTube('${escapeAttr(video.id)}')">
                                ${escapeHtml(video.title)}
                            </div>
                            ${renderVideoActions(video)}
                            <div class="video-meta">
                                <span class="video-duration">${escapeHtml(video.duration_formatted)}</span>
                                <span class="meta-separator">•</span>
                                <span class="video-channel">${escapeHtml(video.channel_name)}</span>
                                <span class="meta-separator">•</span>
                                <span class="video-date">${escapeHtml(video.upload_date_formatted)}</span>
                            </div>
                        </div>
                        <div class="video-footer">
                            <div class="video-source">
                                <span class="video-source-text">${fullSourceText}</span>
                            </div>
                        </div>
                    `;
                    feedContainer.appendChild(div);
                });

                // Show/hide load more button
                if (data.has_more) {
                    const remaining = data.total - (feedOffset + feedLimit);
                    document.getElementById('remainingCount').textContent = remaining;
                    document.getElementById('loadMoreBtn').style.display = 'block';
                } else {
                    document.getElementById('loadMoreBtn').style.display = 'none';
                }

                // Restore scroll after render if requested
                if (savedScrollY !== null) {
                    // Use RAF to ensure DOM is painted before adjusting scroll
                    requestAnimationFrame(() => {
                        window.scrollTo(0, savedScrollY);
                    });
                }

            } catch (error) {
                console.error('Failed to load video feed:', error);
            }
        }

        function loadMoreVideos() {
            feedOffset += feedLimit;
            loadVideoFeed(false);
        }

        function filterFeed() {
            loadVideoFeed(true);
        }

        // Helper: is feed tab currently active/visible?
        function isFeedTabActive() {
            const el = document.getElementById('tab-feed');
            return !!el && el.classList.contains('active');
        }

        // Auto-refresh tick that updates in-place without re-rendering the list
        function autoRefreshFeedTick() {
            // Only refresh if Feed tab is active
            if (!isFeedTabActive()) return;

            // Update only statuses of items that are pending/processing
            updateProcessingStatuses();
        }

        // Find all action nodes that are still pending/processing
        function getProcessingActionNodes() {
            const selector = '#videoFeed .video-grid[data-status="pending"], ' +
                           '#videoFeed .video-grid[data-status="processing"], ' +
                           '#videoFeed .video-grid[data-status="fetching_metadata"], ' +
                           '#videoFeed .video-grid[data-status="fetching_transcript"], ' +
                           '#videoFeed .video-grid[data-status="generating_summary"], ' +
                           '#videoFeed .video-grid[data-status="sending_email"]';
            return Array.from(document.querySelectorAll(selector));
        }

        // Pull fresh details for items in-flight and update their action area without touching layout
        async function updateProcessingStatuses() {
            const nodes = getProcessingActionNodes();
            if (nodes.length === 0) {
                // Nothing in-flight — stop polling
                if (feedRefreshInterval) {
                    clearInterval(feedRefreshInterval);
                    feedRefreshInterval = null;
                }
                return;
            }

            // Fetch each item's latest state; in-flight counts are typically small
            await Promise.all(nodes.map(async (gridEl) => {
                const videoEl = gridEl.closest('.video-item');
                if (!videoEl) return;
                const videoId = videoEl.dataset.videoId;
                try {
                    const resp = await fetch(`/api/videos/${videoId}`);
                    if (!resp.ok) return;
                    const latest = await resp.json();
                    const currentStatus = gridEl.getAttribute('data-status') || '';
                    const newStatus = latest.processing_status || '';

                    // Update metadata fields (title, duration, channel, date) if they've changed
                    // This provides live updates during processing without full page refresh
                    updateVideoMetadata(videoId, latest);

                    if (newStatus !== currentStatus || newStatus === 'success') {
                        // Update labels and buttons (remove old ones, add new ones)
                        const oldLabels = gridEl.querySelector('.video-labels');
                        const oldButtons = gridEl.querySelector('.video-buttons');
                        if (oldLabels) oldLabels.remove();
                        if (oldButtons) oldButtons.remove();

                        // Insert new labels and buttons after title
                        const title = gridEl.querySelector('.video-title');
                        title.insertAdjacentHTML('afterend', renderVideoActions(latest));

                        gridEl.setAttribute('data-status', newStatus);

                        // Update video footer with transcript source if video completed
                        if (newStatus === 'success' && latest.transcript_source) {
                            const footer = videoEl.querySelector('.video-footer .video-source-text');
                            if (footer) {
                                const isManual = latest.source_type === 'via_manual';
                                const sourceInfoText = isManual ? 'manual' : 'channel';
                                footer.textContent = `${sourceInfoText} • ${latest.transcript_source}`;
                            }
                        }
                    }

                    // Check for countdown in logs (for all processing statuses)
                    if (newStatus !== 'success' && newStatus !== 'failed_permanent') {
                        try {
                            const logsResp = await fetch(`/api/videos/${videoId}/logs?lines=200&context=0`);
                            if (logsResp.ok) {
                                const logsData = await logsResp.json();
                                const lines = logsData.lines || [];

                                // Find the latest "Sleeping" log line
                                const sleepingMatch = lines.find(line => line.includes('Sleeping') && line.includes('s '));
                                if (sleepingMatch) {
                                    const countdownMatch = sleepingMatch.match(/Sleeping\s+([\d.]+)s/);
                                    if (countdownMatch) {
                                        const countdown = Math.ceil(parseFloat(countdownMatch[1]));
                                        updateVideoCountdown(videoId, countdown);
                                    }
                                }
                            }
                        } catch (e) {
                            // Ignore log fetch errors
                            console.debug('Log fetch failed for', videoId, e);
                        }
                    }
                } catch (e) {
                    // Ignore transient errors
                    console.debug('Status update failed for', videoId, e);
                }
            }));
        }

        // Update video metadata fields in the DOM when they change
        // This enables live updates during video processing without full page refresh
        function updateVideoMetadata(videoId, latestData) {
            const videoEl = document.querySelector(`#video-${videoId}`);
            if (!videoEl) return { updated: false };

            let hasChanges = false;
            const changes = {};

            // Update title if changed
            const titleEl = videoEl.querySelector('.video-title');
            if (titleEl && latestData.title) {
                const currentTitle = titleEl.textContent.trim();
                if (currentTitle !== latestData.title) {
                    titleEl.textContent = latestData.title;
                    changes.title = { from: currentTitle, to: latestData.title };
                    hasChanges = true;
                }
            }

            // Update duration if changed
            const durationEl = videoEl.querySelector('.video-duration');
            if (durationEl && latestData.duration_formatted) {
                const currentDuration = durationEl.textContent.trim();
                if (currentDuration !== latestData.duration_formatted) {
                    durationEl.textContent = latestData.duration_formatted;
                    changes.duration = { from: currentDuration, to: latestData.duration_formatted };
                    hasChanges = true;
                }
            }

            // Update channel name if changed
            const channelEl = videoEl.querySelector('.video-channel');
            if (channelEl && latestData.channel_name) {
                const currentChannel = channelEl.textContent.trim();
                if (currentChannel !== latestData.channel_name) {
                    channelEl.textContent = latestData.channel_name;
                    changes.channel = { from: currentChannel, to: latestData.channel_name };
                    hasChanges = true;
                }
            }

            // Update upload date if changed
            const dateEl = videoEl.querySelector('.video-date');
            if (dateEl && latestData.upload_date_formatted) {
                const currentDate = dateEl.textContent.trim();
                if (currentDate !== latestData.upload_date_formatted) {
                    dateEl.textContent = latestData.upload_date_formatted;
                    changes.upload_date = { from: currentDate, to: latestData.upload_date_formatted };
                    hasChanges = true;
                }
            }

            // Log changes for debugging (only if something changed)
            if (hasChanges) {
                console.log(`📝 Updated metadata for video ${videoId}:`, changes);
            }

            return { updated: hasChanges, changes };
        }

        function viewChannelFeed(channelId) {
            // Set filter to channel
            document.getElementById('feedChannelFilter').value = channelId;

            // Switch to feed tab
            showTab('feed');

            // Reload feed with filter
            filterFeed();
        }

        function populateChannelFilter() {
            const select = document.getElementById('feedChannelFilter');

            // Keep "All Sources" option
            select.innerHTML = '<option value="">All Sources</option>';

            // Add Manual option
            const manualOption = document.createElement('option');
            manualOption.value = 'manual';
            manualOption.textContent = 'Manual';
            select.appendChild(manualOption);

            // Add each channel
            channels.forEach(id => {
                const name = channelNames[id] || id;
                const option = document.createElement('option');
                option.value = id;
                option.textContent = name;
                select.appendChild(option);
            });
        }

        // Auto-fetch channel name and cache the result
        let fetchTimeout = null;
        let cachedChannelInfo = null; // Cache to avoid redundant fetches

        document.getElementById('channelId').addEventListener('input', async e => {
            const input = e.target.value.trim();

            // Clear cache when input changes
            cachedChannelInfo = null;

            // Clear previous timeout
            if (fetchTimeout) clearTimeout(fetchTimeout);

            // Check if input is empty or too short
            if (!input || input.length < 3) return;

            // Check if it looks like a valid channel ID, URL, or @handle
            const isChannelId = /UC[\w-]{22}/.test(input);
            const isUrl = /youtube\.com/.test(input);
            const isHandle = /^@[\w-]+$/.test(input);

            if (!isChannelId && !isUrl && !isHandle) return;

            const nameInput = document.getElementById('channelName');

            // Debounce: wait 500ms after user stops typing
            fetchTimeout = setTimeout(async () => {
                try {
                    nameInput.value = 'Fetching...';
                    nameInput.disabled = true;

                    const response = await fetch(`/api/fetch-channel-name/${encodeURIComponent(input)}`);

                    if (response.ok) {
                        const data = await response.json();

                        // Cache the result for use in addChannel()
                        cachedChannelInfo = {
                            input: input,
                            channel_id: data.channel_id,
                            channel_name: data.channel_name
                        };

                        nameInput.value = data.channel_name;
                        showStatus(`Found: ${data.channel_name}`, false);
                    } else {
                        nameInput.value = '';
                        cachedChannelInfo = null;
                        console.log('Could not fetch channel name');
                    }
                } catch (error) {
                    nameInput.value = '';
                    cachedChannelInfo = null;
                    console.log('Error fetching channel name:', error);
                } finally {
                    nameInput.disabled = false;
                }
            }, 500);
        });

        // Keyboard shortcuts
        document.getElementById('channelId').addEventListener('keypress', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('channelName').focus();
            }
        });

        document.getElementById('channelName').addEventListener('keypress', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addChannel();
            }
        });

        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                closeModal();
                closeLogsModal();
            }
        });

        document.getElementById('modal').addEventListener('click', e => {
            if (e.target.id === 'modal') closeModal();
        });

        // Close logs modal when clicking outside
        document.getElementById('logsModal').addEventListener('click', e => {
            if (e.target.id === 'logsModal') closeLogsModal();
        });

        // Load on start
        loadYTDLPTiming();
        loadChannels();

        // Validate settings configuration
        validateSettingsConfig();

        // Restore the last active tab from localStorage
        const savedTab = localStorage.getItem('activeTab');
        if (savedTab && ['channels', 'feed', 'settings', 'ai'].includes(savedTab)) {
            // Small delay to ensure the page is fully loaded
            setTimeout(() => {
                showTab(savedTab);
            }, 100);
        }

        // ============================================================================
        // TAB NAVIGATION
        // ============================================================================

        function showTab(tabName) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });

            // Remove active class from all buttons
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.remove('active');
            });

            // Show selected tab
            document.getElementById(`tab-${tabName}`).classList.add('active');

            // Activate button (find the button by tab name if event not available)
            if (event && event.target) {
                event.target.classList.add('active');
            } else {
                // Find the button by searching for matching onclick
                const buttons = document.querySelectorAll('.tab-btn');
                buttons.forEach(btn => {
                    if (btn.getAttribute('onclick') === `showTab('${tabName}')`) {
                        btn.classList.add('active');
                    }
                });
            }

            // Save the current tab to localStorage
            localStorage.setItem('activeTab', tabName);

            // Load data for the tab
            if (tabName === 'feed') {
                loadVideoFeed(true);
            } else if (tabName === 'settings') {
                loadSettings();
            } else if (tabName === 'ai') {
                loadAITab();
            } else if (tabName === 'logs') {
                loadLogsTab();
            }

            // Generate TOC for the new tab (after content is visible)
            // Use setTimeout to ensure DOM is updated
            setTimeout(() => {
                generateTOC();
            }, 50);
        }

        // ============================================================================
        // SETTINGS TAB
        // ============================================================================

        let allSettings = {};

        // Toggle summary length input visibility based on checkbox
        function toggleSummaryLengthInput() {
            const checkbox = document.getElementById('USE_SUMMARY_LENGTH');
            const summaryLengthRow = document.getElementById('summaryLengthRow');

            if (checkbox && summaryLengthRow) {
                summaryLengthRow.style.display = checkbox.checked ? 'block' : 'none';
            }
        }

        // Toggle email fields based on SEND_EMAIL_SUMMARIES setting
        function toggleEmailFields() {
            const sendEmailSelect = document.getElementById('SEND_EMAIL_SUMMARIES');
            const emailFields = document.querySelectorAll('.email-field');

            if (sendEmailSelect && emailFields) {
                const isEnabled = sendEmailSelect.value === 'true';

                emailFields.forEach(field => {
                    // Grey out the entire row
                    field.style.opacity = isEnabled ? '1' : '0.5';
                    field.style.pointerEvents = isEnabled ? 'auto' : 'none';

                    // Disable all inputs and buttons within
                    const inputs = field.querySelectorAll('input, button');
                    inputs.forEach(input => {
                        input.disabled = !isEnabled;
                    });
                });
            }
        }

        /**
         * Toggle visibility of Supadata API key field based on checkbox
         */
        function toggleSupadataFallback() {
            const fallbackCheckbox = document.getElementById('ENABLE_SUPADATA_FALLBACK');
            const supadataApiRow = document.getElementById('supadata-api-row');

            if (fallbackCheckbox && supadataApiRow) {
                const isEnabled = fallbackCheckbox.checked;
                supadataApiRow.style.display = isEnabled ? 'block' : 'none';

                // Show unsaved indicator when checkbox state changes (using centralized utility)
                showUnsavedIndicator('transcript');
            }
        }

        async function loadOpenAIModels(preserveSelection = false) {
            try {
                const modelSelect = document.getElementById('OPENAI_MODEL');

                // Save current selection if requested
                const currentSelection = preserveSelection ? modelSelect.value : null;

                const response = await fetch('/api/openai/models');
                if (!response.ok) throw new Error('Failed to load models');

                const data = await response.json();

                // Clear existing options
                modelSelect.innerHTML = '';

                // Filter to only show chat/text models (exclude image, audio, embedding, moderation, etc.)
                const textModels = data.models.filter(model => {
                    const id = model.id.toLowerCase();
                    return (
                        // Include GPT chat models
                        (id.startsWith('gpt-') && !id.includes('instruct')) ||
                        id.startsWith('o1') ||
                        id.startsWith('o3')
                    ) && (
                        // Exclude non-text models
                        !id.includes('dall-e') &&
                        !id.includes('whisper') &&
                        !id.includes('tts') &&
                        !id.includes('embedding') &&
                        !id.includes('moderation') &&
                        !id.includes('vision') &&
                        !id.includes('audio')
                    );
                });

                // Add filtered models to dropdown
                textModels.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model.id;
                    option.textContent = model.name;
                    modelSelect.appendChild(option);
                });

                // Restore previous selection if it still exists in the new list
                if (preserveSelection && currentSelection) {
                    const modelExists = textModels.some(m => m.id === currentSelection);
                    if (modelExists) {
                        modelSelect.value = currentSelection;
                    }
                }

                console.log(`Loaded ${textModels.length} text models (filtered from ${data.models.length} total) from ${data.source}`);

            } catch (error) {
                console.error('Failed to load OpenAI models:', error);
                // Add default fallback options
                const modelSelect = document.getElementById('OPENAI_MODEL');
                const currentSelection = preserveSelection ? modelSelect.value : null;

                modelSelect.innerHTML = `
                    <option value="gpt-4o">GPT-4o (Latest, Most Capable)</option>
                    <option value="gpt-4o-mini">GPT-4o Mini (Fast & Affordable)</option>
                    <option value="gpt-4-turbo">GPT-4 Turbo</option>
                    <option value="gpt-4">GPT-4</option>
                    <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                `;

                // Try to restore selection
                if (preserveSelection && currentSelection) {
                    const option = modelSelect.querySelector(`option[value="${currentSelection}"]`);
                    if (option) {
                        modelSelect.value = currentSelection;
                    }
                }
            }
        }

        async function loadSettings() {
            try {
                // Set flag to prevent showing unsaved indicators during programmatic value setting
                isLoadingSettings = true;

                // Load settings first to get the saved OPENAI_MODEL value
                const response = await fetch('/api/settings');
                if (!response.ok) throw new Error('Failed to load settings');

                const data = await response.json();
                allSettings = data;

                // Load OpenAI models (this will populate the dropdown)
                await loadOpenAIModels();

                // Populate .env settings
                for (const [key, info] of Object.entries(data.env)) {
                    const element = document.getElementById(key);

                    if (key === 'OPENAI_API_KEY' || key === 'SMTP_PASS' || key === 'SUPADATA_API_KEY') {
                        // For password fields, show masked value in the field and placeholder
                        if (element) {
                            if (info.masked && info.masked !== '') {
                                // Show masked value in the field so user knows it's saved
                                element.value = info.masked;
                                element.placeholder = 'Enter new key to update';
                            } else {
                                let placeholder = '16-character app password';
                                if (key === 'OPENAI_API_KEY') placeholder = 'sk-...';
                                else if (key === 'SUPADATA_API_KEY') placeholder = 'sd_...';
                                element.placeholder = placeholder;
                            }
                        }
                    } else if (key === 'OPENAI_MODEL') {
                        // Handle OPENAI_MODEL separately - set after models are loaded
                        if (element && info.value) {
                            // Check if the saved model exists in the dropdown
                            const option = element.querySelector(`option[value="${info.value}"]`);
                            if (option) {
                                element.value = info.value;
                                console.log(`Set OPENAI_MODEL to saved value: ${info.value}`);
                            } else {
                                // Saved model not available, keep first option selected
                                console.warn(`Saved model "${info.value}" not found in available models, using default: ${element.value}`);
                            }
                        }
                    } else if (element) {
                        // Handle checkbox elements (they need .checked, not .value)
                        if (element.type === 'checkbox') {
                            element.checked = (info.value || info.default) === 'true';
                        } else if (info.type === 'enum') {
                            element.value = info.value || info.default;
                        } else {
                            element.value = info.value || info.default;
                        }
                    }
                }

                // Populate config settings
                const config = data.config;
                document.getElementById('SUMMARY_LENGTH').value = config.SUMMARY_LENGTH || '500';
                document.getElementById('USE_SUMMARY_LENGTH').checked = config.USE_SUMMARY_LENGTH === 'true';
                document.getElementById('SKIP_SHORTS').checked = config.SKIP_SHORTS === 'true';

                // Load log retention days
                const logRetentionDays = data.env['LOG_RETENTION_DAYS']?.value || '7';
                const logRetentionInput = document.getElementById('logRetentionDays');
                if (logRetentionInput) {
                    logRetentionInput.value = logRetentionDays;
                }

                // Toggle summary length input visibility
                toggleSummaryLengthInput();

                // Toggle email fields based on SEND_EMAIL_SUMMARIES
                toggleEmailFields();

                // Toggle Supadata API key field based on fallback checkbox
                toggleSupadataFallback();

            } catch (error) {
                showSettingsStatus('Failed to load settings', true);
                console.error(error);
            } finally {
                // Always reset the flag, even if there was an error
                isLoadingSettings = false;
            }
        }

        function showSettingsStatus(msg, isError, autoHide = true) {
            const status = document.getElementById('settingsStatus');
            if (!status) {
                console.warn('settingsStatus element not found');
                return;
            }
            status.textContent = msg;
            status.className = isError ? 'status error show' : 'status show';
            if (autoHide) {
                setTimeout(() => status.classList.remove('show'), isError ? 5000 : 3000);
            }
        }

        function showAdvancedStatus(msg, isError) {
            const status = document.getElementById('advancedStatus');
            if (!status) {
                console.warn('advancedStatus element not found');
                return;
            }
            status.textContent = msg;
            status.className = isError ? 'status error show' : 'status show';
            setTimeout(() => status.classList.remove('show'), 5000);
        }

        async function saveAllSettings(buttonElement) {
            const button = buttonElement;

            try {
                const settingsToSave = {};

                // Get all .env settings (only include non-empty values)
                const targetEmail = document.getElementById('TARGET_EMAIL').value.trim();
                if (targetEmail) settingsToSave['TARGET_EMAIL'] = targetEmail;

                const smtpUser = document.getElementById('SMTP_USER').value.trim();
                if (smtpUser) settingsToSave['SMTP_USER'] = smtpUser;

                const checkInterval = document.getElementById('CHECK_INTERVAL_HOURS').value.trim();
                if (checkInterval) settingsToSave['CHECK_INTERVAL_HOURS'] = checkInterval;

                settingsToSave['SEND_EMAIL_SUMMARIES'] = document.getElementById('SEND_EMAIL_SUMMARIES').value;

                // Get password fields (only save if they have new values, not masked values)
                const smtpPass = document.getElementById('SMTP_PASS').value.trim();
                // Don't save if it's masked (dots) or empty
                if (smtpPass && !smtpPass.includes('•')) {
                    settingsToSave['SMTP_PASS'] = smtpPass;
                }

                // Get config settings (only include non-empty values)
                settingsToSave['SKIP_SHORTS'] = document.getElementById('SKIP_SHORTS').checked ? 'true' : 'false';

                // Get Supadata fallback settings
                settingsToSave['ENABLE_SUPADATA_FALLBACK'] = document.getElementById('ENABLE_SUPADATA_FALLBACK').checked ? 'true' : 'false';

                // Get Supadata API key if changed (don't save masked values)
                const supadataKey = document.getElementById('SUPADATA_API_KEY').value.trim();
                const isNewSupadataKey = supadataKey && !supadataKey.includes('***') && !supadataKey.includes('•');

                // Only save if it's a new key (not masked or empty)
                if (isNewSupadataKey) {
                    settingsToSave['SUPADATA_API_KEY'] = supadataKey;
                }

                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings: settingsToSave })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail?.message || 'Failed to save');
                }

                const result = await response.json();

                // Show confirmation in button
                if (button) {
                    showButtonConfirmation(button, '✓ Saved!');
                }

                // Hide unsaved indicators for sections saved by this function
                hideUnsavedIndicators(['email', 'video', 'transcript']);

                // Show restart notification after button confirmation completes
                if (result.restart_required) {
                    setTimeout(() => {
                        showRestartNotification();
                    }, 2000);
                }

            } catch (error) {
                // Show error in button
                if (button) {
                    const originalText = button.textContent;
                    button.textContent = `❌ ${error.message}`;
                    button.style.backgroundColor = '#dc2626'; // Red
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.style.backgroundColor = '';
                    }, 3000);
                }
                console.error(error);
            }
        }

        // Save logging settings
        async function saveLoggingSettings() {
            const retentionDays = parseInt(document.getElementById('logRetentionDays').value);

            // Validate
            if (retentionDays < 1 || retentionDays > 30) {
                showStatus('Log retention must be between 1 and 30 days', true);
                return;
            }

            try {
                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        settings: {
                            LOG_RETENTION_DAYS: retentionDays.toString()
                        }
                    })
                });

                if (response.ok) {
                    hideUnsavedIndicator('logging');
                    showStatus('Logging settings saved successfully', false);
                } else {
                    throw new Error('Failed to save settings');
                }
            } catch (error) {
                showStatus('Failed to save logging settings', true);
            }
        }

        function showRestartNotification() {
            // Hide status message
            const status = document.getElementById('settingsStatus');
            if (status) {
                status.classList.remove('show');
            }

            // Show restart notification
            document.getElementById('restartNotification').style.display = 'flex';
        }

        // ============================================================================
        // CREDENTIAL TESTING
        // ============================================================================

        async function testOpenAIKey() {
            const resultDiv = document.getElementById('openai-test-result');
            resultDiv.innerHTML = '<div class="test-result">Testing...</div>';

            try {
                const apiKey = document.getElementById('OPENAI_API_KEY').value.trim();

                // If the field contains the masked value, don't send it - let backend use saved value
                const testValue = (apiKey && !apiKey.includes('***')) ? apiKey : undefined;

                const response = await fetch('/api/settings/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        credential_type: 'openai',
                        test_value: testValue
                    })
                });

                const result = await response.json();

                if (result.success) {
                    resultDiv.innerHTML = `<div class="test-result success">${result.message}</div>`;
                } else {
                    resultDiv.innerHTML = `<div class="test-result error">${result.message}</div>`;
                }

            } catch (error) {
                resultDiv.innerHTML = `<div class="test-result error">❌ Test failed: ${error.message}</div>`;
            }
        }

        async function testSmtpCredentials() {
            const resultDiv = document.getElementById('smtp-test-result');
            resultDiv.innerHTML = '<div class="test-result">Testing...</div>';

            try {
                const smtpUser = document.getElementById('SMTP_USER').value.trim();
                const smtpPass = document.getElementById('SMTP_PASS').value.trim();

                // If fields contain masked values, don't send them - let backend use saved values
                const testUser = smtpUser || undefined;
                const testPass = (smtpPass && !smtpPass.includes('•')) ? smtpPass : undefined;

                const response = await fetch('/api/settings/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        credential_type: 'smtp',
                        test_user: testUser,
                        test_pass: testPass
                    })
                });

                const result = await response.json();

                if (result.success) {
                    resultDiv.innerHTML = `<div class="test-result success">${result.message}</div>`;
                } else {
                    resultDiv.innerHTML = `<div class="test-result error">${result.message}</div>`;
                }

            } catch (error) {
                resultDiv.innerHTML = `<div class="test-result error">❌ Test failed: ${error.message}</div>`;
            }
        }

        /**
         * Send test email to TARGET_EMAIL address
         * Tests end-to-end email delivery using configured settings
         * REPLACES: testSmtpCredentials() - provides more comprehensive testing
         */
        async function sendTestEmail() {
            const resultDiv = document.getElementById('smtp-test-result'); // Reuse existing div

            // Show loading state
            resultDiv.innerHTML = '<div class="test-result">Sending test email...</div>';

            try {
                // Get current form field values
                const targetEmail = document.getElementById('TARGET_EMAIL')?.value.trim();
                const smtpUser = document.getElementById('SMTP_USER')?.value.trim();
                const smtpPass = document.getElementById('SMTP_PASS')?.value.trim();

                // Build request body with form values (allows testing before saving)
                const requestBody = {};
                if (targetEmail) requestBody.target_email = targetEmail;
                if (smtpUser) requestBody.smtp_user = smtpUser;
                // Only send password if it's not masked (dots) - let backend use saved value
                if (smtpPass && !smtpPass.includes('•')) {
                    requestBody.smtp_pass = smtpPass;
                }

                const response = await fetch('/api/settings/send-test-email', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(requestBody)
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const result = await response.json();

                if (result.success) {
                    resultDiv.innerHTML = `<div class="test-result success">${result.message}</div>`;
                } else {
                    resultDiv.innerHTML = `<div class="test-result error">${result.message}</div>`;
                }

                // Auto-clear message after 10 seconds
                setTimeout(() => {
                    resultDiv.innerHTML = '';
                }, 10000);

            } catch (error) {
                console.error('Test email error:', error);
                resultDiv.innerHTML = `<div class="test-result error">❌ Failed to send test email: ${error.message}</div>`;

                // Auto-clear error after 10 seconds
                setTimeout(() => {
                    resultDiv.innerHTML = '';
                }, 10000);
            }
        }

        // ============================================================================
        // RESTART APPLICATION
        // ============================================================================

        async function restartApplication() {
            const notification = document.getElementById('restartNotification');

            // Update notification text
            notification.innerHTML = 'Restarting... <button class="btn-restart-inline" disabled style="opacity: 0.6;">Restarting...</button>';

            try {
                const response = await fetch('/api/settings/restart', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                const result = await response.json();

                if (result.success) {
                    notification.innerHTML = `✅ ${result.message} - Reloading page in 5 seconds...`;
                    // Only reload if restart was actually successful
                    setTimeout(() => {
                        window.location.reload();
                    }, 5000);
                } else {
                    notification.innerHTML = `❌ ${result.message} <button onclick="restartApplication()" class="btn-restart-inline">Try Again</button>`;
                }
            } catch (error) {
                // Server likely already restarted - this is expected
                console.log('Restart triggered, server restarting...');
                notification.innerHTML = `✅ Server restarting... Reloading page in 5 seconds...`;
                // Only reload after server restart
                setTimeout(() => {
                    window.location.reload();
                }, 5000);
            }
        }

        // ============================================================================
        // AI TAB (CREDENTIALS + PROMPT EDITOR)
        // ============================================================================

        let defaultPrompt = `You are summarizing a YouTube video. Create a concise summary that:
1. Captures the main points in 2-3 paragraphs
2. Highlights what's valuable or interesting
3. Mentions any actionable takeaways
4. Indicates who would benefit from watching

Keep the tone conversational and focus on value.

Title: {title}
Duration: {duration}
Transcript: {transcript}`;

        function showAIStatus(msg, isError) {
            const status = document.getElementById('aiStatus');
            if (!status) {
                console.warn('aiStatus element not found');
                return;
            }
            status.textContent = msg;
            status.className = isError ? 'status error show' : 'status show';
            setTimeout(() => status.classList.remove('show'), isError ? 5000 : 3000);
        }

        async function loadAITab() {
            // Load settings (this will also load models and apply the saved selection)
            await loadSettings();

            // Load prompt
            await loadPrompt();
        }

        async function loadPrompt() {
            try {
                // Set flag to prevent showing unsaved indicators during programmatic value setting
                isLoadingSettings = true;

                const response = await fetch('/api/settings/prompt');
                if (!response.ok) throw new Error('Failed to load prompt');

                const data = await response.json();
                document.getElementById('promptEditor').value = data.prompt || defaultPrompt;

            } catch (error) {
                showAIStatus('Failed to load prompt', true);
                console.error(error);
            } finally {
                // Always reset the flag, even if there was an error
                isLoadingSettings = false;
            }
        }

        async function savePrompt(buttonElement) {
            const button = buttonElement;
            const prompt = document.getElementById('promptEditor').value.trim();

            if (!prompt) {
                showAIStatus('Prompt cannot be empty', true);
                return;
            }

            if (prompt.length < 10) {
                showAIStatus('Prompt is too short', true);
                return;
            }

            try {
                const response = await fetch('/api/settings/prompt', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to save');
                }

                // Show confirmation in button
                if (button) {
                    showButtonConfirmation(button, '✓ Saved!');
                }

                // Hide unsaved indicator
                hideUnsavedIndicator('prompt');

            } catch (error) {
                // Show error in button
                if (button) {
                    const originalText = button.textContent;
                    button.textContent = `❌ ${error.message}`;
                    button.style.backgroundColor = '#dc2626'; // Red
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.style.backgroundColor = '';
                    }, 3000);
                }
                console.error(error);
            }
        }

        function resetPrompt() {
            if (confirm('Are you sure you want to reset the prompt to default?')) {
                document.getElementById('promptEditor').value = defaultPrompt;
                showAIStatus('Prompt reset to default. Click Save to apply.', false);
            }
        }

        async function saveAICredentials(buttonElement) {
            const button = buttonElement;

            try {
                const settingsToSave = {};

                // Get OpenAI credentials
                settingsToSave['OPENAI_MODEL'] = document.getElementById('OPENAI_MODEL').value;

                // Get API key if changed (don't save masked values)
                const openaiKey = document.getElementById('OPENAI_API_KEY').value.trim();
                const isNewApiKey = openaiKey && !openaiKey.includes('***');

                // Don't save if it's the masked value or empty
                if (isNewApiKey) {
                    settingsToSave['OPENAI_API_KEY'] = openaiKey;
                }

                // Get summary length settings (now in AI tab)
                const summaryLength = document.getElementById('SUMMARY_LENGTH').value.trim();
                if (summaryLength) settingsToSave['SUMMARY_LENGTH'] = summaryLength;

                settingsToSave['USE_SUMMARY_LENGTH'] = document.getElementById('USE_SUMMARY_LENGTH').checked ? 'true' : 'false';

                // Get Supadata fallback settings
                settingsToSave['ENABLE_SUPADATA_FALLBACK'] = document.getElementById('ENABLE_SUPADATA_FALLBACK').checked ? 'true' : 'false';

                // Get Supadata API key if changed (don't save masked values)
                const supadataKey = document.getElementById('SUPADATA_API_KEY').value.trim();
                const isNewSupadataKey = supadataKey && !supadataKey.includes('***') && !supadataKey.includes('•');

                // Only save if it's a new key (not masked or empty)
                if (isNewSupadataKey) {
                    settingsToSave['SUPADATA_API_KEY'] = supadataKey;
                }

                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings: settingsToSave })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail?.message || 'Failed to save');
                }

                // If we saved a new API key, reload available models (preserve current selection)
                if (isNewApiKey) {
                    await loadOpenAIModels(true);
                }

                // Show confirmation in button
                if (button) {
                    showButtonConfirmation(button, '✓ Saved!');
                }

                // Hide unsaved indicator
                hideUnsavedIndicator('ai-credentials');

            } catch (error) {
                // Show error in button
                if (button) {
                    const originalText = button.textContent;
                    button.textContent = `❌ ${error.message}`;
                    button.style.backgroundColor = '#dc2626'; // Red
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.style.backgroundColor = '';
                    }, 3000);
                }
                console.error(error);
            }
        }

        // Track all settings changes by section
        const trackableInputs = document.querySelectorAll('.trackable-input');
        trackableInputs.forEach(input => {
            const showIndicator = () => {
                const section = input.getAttribute('data-section');
                showUnsavedIndicator(section);  // Use centralized utility function
            };

            // Track both input and change events (input for text fields, change for select/checkbox)
            input.addEventListener('input', showIndicator);
            input.addEventListener('change', showIndicator);
        });

        // Auto-load OpenAI models when API key is entered
        const apiKeyInput = document.getElementById('OPENAI_API_KEY');
        if (apiKeyInput) {
            let modelLoadTimeout;

            apiKeyInput.addEventListener('input', function() {
                clearTimeout(modelLoadTimeout);
                const apiKey = this.value.trim();

                // Check if it looks like a valid OpenAI key (starts with sk-, not masked, sufficient length)
                if (apiKey && apiKey.startsWith('sk-') && !apiKey.includes('***') && !apiKey.includes('•') && apiKey.length > 20) {
                    // Debounce: wait 1.5 seconds after user stops typing
                    modelLoadTimeout = setTimeout(async () => {
                        console.log('Auto-loading OpenAI models for new API key...');

                        // Show loading state in model dropdown
                        const modelSelect = document.getElementById('OPENAI_MODEL');
                        if (modelSelect) {
                            const originalHTML = modelSelect.innerHTML;
                            modelSelect.innerHTML = '<option value="">Loading models...</option>';
                            modelSelect.disabled = true;

                            try {
                                // Temporarily save the API key to test it
                                await fetch('/api/settings', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ settings: { 'OPENAI_API_KEY': apiKey } })
                                });

                                // Load the available models
                                await loadOpenAIModels(true);

                                // Re-enable the dropdown after successful load
                                modelSelect.disabled = false;
                            } catch (error) {
                                console.error('Failed to load models:', error);
                                modelSelect.innerHTML = originalHTML;
                                modelSelect.disabled = false;
                            }
                        }
                    }, 1500);
                }
            });
        }

        // ============================================================================
        // VIDEO FEED ENHANCEMENTS
        // ============================================================================

        function getStatusLabel(status) {
            const labels = {
                'pending': '⏳ Waiting to start',
                'fetching_metadata': '📊 Fetching video info',
                'fetching_transcript': '📝 Fetching transcript',
                'generating_summary': '🤖 Generating AI summary',
                'sending_email': '📧 Sending email',
                'processing': '⚙️ Processing video',
                'success': '✅ Completed',
                'failed_transcript': '<i class="iconoir-cancel"></i> Transcript unavailable',
                'failed_ai': '<i class="iconoir-cancel"></i> AI generation failed',
                'failed_email': '<i class="iconoir-cancel"></i> Email delivery failed',
                'failed_permanent': '<i class="iconoir-cancel"></i> Failed after 3 retries',
                'failed_stopped': '⏹️ Stopped by user'
            };
            return labels[status] || status;
        }

        function getStepIndicator(status) {
            const steps = {
                'pending': '1/4',
                'fetching_metadata': '1/4',
                'fetching_transcript': '2/4',
                'generating_summary': '3/4',
                'sending_email': '4/4'
            };
            return steps[status] || null;
        }

        function renderVideoActions(video) {
            const status = video.processing_status;
            const retryCount = video.retry_count || 0;
            let labelsHtml = '<div class="video-labels">';
            let buttonsHtml = '<div class="video-buttons">';

            if (status === 'success') {
                // Labels row - only show email label if email was actually sent
                if (video.email_sent) {
                    labelsHtml += `<span class="label-status label-email-sent" title="Email sent successfully"><i class="iconoir-send-mail"></i> Email sent</span>`;
                }

                // Buttons row
                buttonsHtml += `<button class="btn-read-summary" onclick="showSummary('${escapeAttr(video.id)}')">Read Summary</button>`;
                buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${escapeAttr(video.id)}')">Logs</button>`;

            } else if (status === 'pending') {
                labelsHtml += `<span class="label-status label-pending">${getStatusLabel('pending')}</span>`;
                // Show step indicator
                const stepIndicator = getStepIndicator(status);
                if (stepIndicator) {
                    labelsHtml += `<span class="label-status label-step">${stepIndicator}</span>`;
                }
                // Show retry count only if it's actually a retry (> 1, not first attempt)
                if (retryCount > 1) {
                    labelsHtml += `<span class="label-status label-warning" title="Retry attempt ${retryCount} of 3">Retry ${retryCount}/3</span>`;
                }
                // Add Stop and Logs buttons for pending status
                buttonsHtml += `<button class="btn-stop" onclick="stopProcessing('${escapeAttr(video.id)}')">Stop</button>`;
                buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${escapeAttr(video.id)}')">Logs</button>`;
            } else if (status === 'processing' || status === 'fetching_metadata' || status === 'fetching_transcript' || status === 'generating_summary' || status === 'sending_email') {
                labelsHtml += `<span class="label-status label-processing">${getStatusLabel(status)}</span>`;
                // Show step indicator
                const stepIndicator = getStepIndicator(status);
                if (stepIndicator) {
                    labelsHtml += `<span class="label-status label-step">${stepIndicator}</span>`;
                }
                // Show retry count only if it's actually a retry (> 1, not first attempt)
                if (retryCount > 1) {
                    labelsHtml += `<span class="label-status label-warning" title="Retry attempt ${retryCount} of 3">Retry ${retryCount}/3</span>`;
                }
                // Add Stop button for videos being processed
                buttonsHtml += `<button class="btn-stop" onclick="stopProcessing('${escapeAttr(video.id)}')">Stop</button>`;
                buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${escapeAttr(video.id)}')">Logs</button>`;
            } else if (status === 'failed_permanent') {
                // Permanently failed after max retries
                const errorTitle = video.error_message || 'Max retries exceeded';
                labelsHtml += `<span class="label-status label-error" title="${escapeAttr(errorTitle)}">Failed</span>`;
                labelsHtml += `<span class="label-status label-error" title="Max retries reached">3/3</span>`;

                // Force retry option for permanent failures
                buttonsHtml += `<button class="btn-retry" onclick="forceRetryVideo('${escapeAttr(video.id)}')">Force Retry</button>`;
                buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${escapeAttr(video.id)}')">Logs</button>`;
            } else if (status === 'failed_stopped') {
                // User stopped processing
                labelsHtml += `<span class="label-status label-error" title="Processing stopped by user">Stopped</span>`;

                buttonsHtml += `<button class="btn-retry" onclick="retryVideo('${escapeAttr(video.id)}')">Retry</button>`;
                buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${escapeAttr(video.id)}')">Logs</button>`;
            } else if (status && status.startsWith('failed_')) {
                // Parse specific error type from status
                let errorType = 'Failed';
                const errorTitle = video.error_message || 'Processing failed';

                if (status === 'failed_transcript') {
                    errorType = 'Transcript';
                } else if (status === 'failed_ai') {
                    errorType = 'AI';
                } else if (status === 'failed_email') {
                    errorType = 'Email';
                }

                // Labels row
                labelsHtml += `<span class="label-status label-error" title="${escapeAttr(errorTitle)}">${errorType}</span>`;
                // Show retry count (different display for failed states)
                if (retryCount > 0) {
                    labelsHtml += `<span class="label-status label-warning" title="Failed after ${retryCount} attempts">Attempt ${retryCount}/3</span>`;
                }

                // Buttons row
                buttonsHtml += `<button class="btn-retry" onclick="retryVideo('${escapeAttr(video.id)}')">Retry</button>`;
                buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${escapeAttr(video.id)}')">Logs</button>`;
            }

            // Add delete button for manually added videos (all statuses)
            if (video.source_type === 'via_manual') {
                buttonsHtml += `<button class="btn-delete" onclick="confirmDeleteVideo('${escapeAttr(video.id)}', '${escapeAttr(video.title)}')">Delete</button>`;
            }

            labelsHtml += '</div>';
            buttonsHtml += '</div>';

            // Return both rows combined
            return labelsHtml + buttonsHtml;
        }

        async function refreshLogsContent() {
            if (!currentLogsVideoId) return;

            try {
                const resp = await fetch(`/api/videos/${currentLogsVideoId}/logs?lines=1200&context=4`);
                if (!resp.ok) return;
                const data = await resp.json();

                const status = data.status || '';
                const lines = data.lines || [];
                const message = data.message || '';

                // Parse countdown from latest "Sleeping" log line
                const sleepingMatch = lines.find(line => line.includes('Sleeping') && line.includes('s '));
                if (sleepingMatch) {
                    const countdownMatch = sleepingMatch.match(/Sleeping\s+([\d.]+)s/);
                    if (countdownMatch) {
                        const countdown = Math.ceil(parseFloat(countdownMatch[1]));
                        updateVideoCountdown(currentLogsVideoId, countdown);
                    }
                }

                // Update modal content
                const statusEl = document.getElementById('logsStatus');
                const bodyEl = document.getElementById('logsBody');

                if (statusEl) statusEl.textContent = status ? `Status: ${status}` : '';

                if (lines.length > 0) {
                    bodyEl.textContent = lines.join('\n');
                } else {
                    bodyEl.textContent = message || 'No relevant log lines found.';
                }

            } catch (e) {
                console.debug('Failed to refresh logs:', e);
            }
        }

        async function showVideoLogs(videoId) {
            try {
                // Store video ID for refresh
                currentLogsVideoId = videoId;

                const resp = await fetch(`/api/videos/${videoId}/logs?lines=1200&context=4`);
                if (!resp.ok) throw new Error('Failed to load logs');
                const data = await resp.json();

                const title = data.title || videoId;
                const status = data.status || '';
                const lines = data.lines || [];
                const message = data.message || '';

                // Populate modal
                const titleEl = document.getElementById('logsTitle');
                const statusEl = document.getElementById('logsStatus');
                const bodyEl = document.getElementById('logsBody');

                if (titleEl) titleEl.textContent = `Logs: ${title}`;
                if (statusEl) statusEl.textContent = status ? `Status: ${status}` : '';

                if (lines.length > 0) {
                    bodyEl.textContent = lines.join('\n');
                } else {
                    bodyEl.textContent = message || 'No relevant log lines found.';
                }

                document.getElementById('logsModal').classList.add('show');

                // Start auto-refresh every 5 seconds
                if (logsRefreshInterval) {
                    clearInterval(logsRefreshInterval);
                }
                logsRefreshInterval = setInterval(refreshLogsContent, 5000);

            } catch (e) {
                showStatus('Failed to load logs', true);
                console.error(e);
            }
        }

        function closeLogsModal() {
            const modal = document.getElementById('logsModal');
            if (modal) modal.classList.remove('show');

            // Stop auto-refresh
            if (logsRefreshInterval) {
                clearInterval(logsRefreshInterval);
                logsRefreshInterval = null;
            }
            currentLogsVideoId = null;
        }

        async function showSummary(videoId) {
            try {
                // Fetch video details with summary
                const response = await fetch(`/api/videos/${videoId}`);
                if (!response.ok) throw new Error('Failed to load summary');

                const video = await response.json();

                // Populate modal
                document.getElementById('summaryTitle').textContent = video.title;
                document.getElementById('summaryChannel').textContent = video.channel_name;
                document.getElementById('summaryDuration').textContent = video.duration_formatted || 'Unknown';
                document.getElementById('summaryViews').textContent = video.view_count_formatted || 'Unknown';
                document.getElementById('summaryUploadDate').textContent = video.upload_date_formatted || 'Unknown';
                document.getElementById('summaryText').textContent = video.summary_text || 'No summary available';
                document.getElementById('summaryYoutubeLink').href = `https://www.youtube.com/watch?v=${video.id}`;

                // Show modal
                document.getElementById('summaryModal').classList.add('show');

            } catch (error) {
                showStatus('Failed to load summary', true);
                console.error(error);
            }
        }

        function closeSummaryModal() {
            document.getElementById('summaryModal').classList.remove('show');
        }

        function openYouTube(videoId) {
            window.open(`https://www.youtube.com/watch?v=${videoId}`, '_blank');
        }

        async function retryVideo(videoId) {
            try {
                // Immediately update UI to show pending state
                const actionsContainer = document.getElementById(`video-actions-${videoId}`);
                if (actionsContainer) {
                    // Get current retry count from the element or default to 0
                    const currentRetryCount = parseInt(actionsContainer.dataset.retryCount || '0');
                    const newRetryCount = currentRetryCount + 1;

                    // Update to pending state immediately with updated retry count
                    let labelsHtml = '<div class="video-labels">';
                    labelsHtml += '<span class="label-status label-pending">Pending</span>';
                    if (newRetryCount > 0) {
                        labelsHtml += `<span class="label-status label-warning" title="Retry attempt ${newRetryCount} of 3">${newRetryCount}/3</span>`;
                    }
                    labelsHtml += '</div>';
                    let buttonsHtml = '<div class="video-buttons">';
                    buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${videoId}')">Logs</button>`;
                    buttonsHtml += '</div>';

                    actionsContainer.innerHTML = labelsHtml + buttonsHtml;
                    actionsContainer.dataset.status = 'pending';
                    actionsContainer.dataset.retryCount = newRetryCount.toString();
                }

                const response = await fetch(`/api/videos/${videoId}/retry`, {
                    method: 'POST'
                });

                if (response.ok) {
                    showStatus('Video queued for reprocessing', false);
                    // Update status after a delay to catch processing state
                    setTimeout(() => updateProcessingStatuses(), 2000);
                    // Ensure periodic updates run until processing completes
                    if (!feedRefreshInterval) {
                        feedRefreshInterval = setInterval(autoRefreshFeedTick, 5000);
                    }
                } else {
                    // Revert UI if request failed
                    throw new Error('Failed to retry');
                }
            } catch (error) {
                showStatus('Failed to queue video for retry', true);
                console.error(error);
                // Try to refresh the status to revert changes
                updateProcessingStatuses();
            }
        }

        async function stopProcessing(videoId) {
            try {
                // Immediately update UI to show stopped state
                const actionsContainer = document.getElementById(`video-actions-${videoId}`);
                if (actionsContainer) {
                    let labelsHtml = '<div class="video-labels">';
                    labelsHtml += '<span class="label-status label-error" title="Processing stopped by user">Stopped</span>';
                    labelsHtml += '</div>';
                    let buttonsHtml = '<div class="video-buttons">';
                    buttonsHtml += `<button class="btn-retry" onclick="retryVideo('${videoId}')">Retry</button>`;
                    buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${videoId}')">Logs</button>`;
                    buttonsHtml += '</div>';

                    actionsContainer.innerHTML = labelsHtml + buttonsHtml;
                    actionsContainer.dataset.status = 'failed_stopped';
                }

                const response = await fetch(`/api/videos/${videoId}/stop`, {
                    method: 'POST'
                });

                if (response.ok) {
                    showStatus('Processing stopped', false);
                    // Update status after a moment to sync with server
                    setTimeout(() => updateProcessingStatuses(), 1000);
                } else {
                    throw new Error('Failed to stop processing');
                }
            } catch (error) {
                showStatus('Failed to stop processing', true);
                console.error(error);
                // Try to refresh the status to revert changes
                updateProcessingStatuses();
            }
        }

        async function forceRetryVideo(videoId) {
            // Reset retry count and retry
            try {
                // Immediately update UI to show pending state with reset retry count
                const actionsContainer = document.getElementById(`video-actions-${videoId}`);
                if (actionsContainer) {
                    // Force retry resets count to 1
                    let labelsHtml = '<div class="video-labels">';
                    labelsHtml += '<span class="label-status label-pending">Pending</span>';
                    labelsHtml += '<span class="label-status label-warning" title="Retry attempt 1 of 3">1/3</span>';
                    labelsHtml += '</div>';
                    let buttonsHtml = '<div class="video-buttons">';
                    buttonsHtml += `<button class="btn-logs" onclick="showVideoLogs('${videoId}')">Logs</button>`;
                    buttonsHtml += '</div>';

                    actionsContainer.innerHTML = labelsHtml + buttonsHtml;
                    actionsContainer.dataset.status = 'pending';
                    actionsContainer.dataset.retryCount = '1';
                }

                const response = await fetch(`/api/videos/${videoId}/force-retry`, {
                    method: 'POST'
                });

                if (response.ok) {
                    showStatus('Video queued for force retry', false);
                    // Update status after a delay to catch processing state
                    setTimeout(() => updateProcessingStatuses(), 2000);
                    if (!feedRefreshInterval) {
                        feedRefreshInterval = setInterval(autoRefreshFeedTick, 5000);
                    }
                } else {
                    throw new Error('Failed to force retry');
                }
            } catch (error) {
                showStatus('Failed to force retry video', true);
                console.error(error);
                // Try to refresh the status to revert changes
                updateProcessingStatuses();
            }
        }

        function confirmDeleteVideo(videoId, videoTitle) {
            // Show confirmation modal
            const modal = document.getElementById('modal');
            const modalTitle = document.getElementById('modalTitle');
            const modalMessage = document.getElementById('modalMessage');
            const confirmBtn = document.getElementById('modalConfirmBtn');

            modalTitle.textContent = 'Delete Video';
            modalMessage.textContent = `Are you sure you want to permanently delete "${videoTitle}"? This action cannot be undone.`;
            confirmBtn.textContent = 'Delete';
            confirmBtn.onclick = () => deleteVideo(videoId);

            modal.classList.add('show');
        }

        async function deleteVideo(videoId) {
            closeModal();

            try {
                const response = await fetch(`/api/videos/${videoId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    showStatus('Video deleted successfully', false);

                    // Remove video element from DOM
                    const videoElement = document.getElementById(`video-${videoId}`);
                    if (videoElement) {
                        videoElement.remove();
                    }

                    // Reload feed to update count
                    setTimeout(() => loadVideoFeed(true, true), 500);
                } else {
                    throw new Error('Failed to delete video');
                }
            } catch (error) {
                showStatus('Failed to delete video', true);
                console.error(error);
            }
        }

        async function checkNow() {
            const btn = event.target;
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Checking...';

            try {
                const response = await fetch('/api/videos/process-now', {
                    method: 'POST'
                });

                if (response.ok) {
                    showStatus('Video check started! Updating...', false);
                    // Politely refresh to include any new processing videos without jumping
                    setTimeout(() => loadVideoFeed(true, true), 2000);
                    // Ensure periodic status updates start
                    if (!feedRefreshInterval) {
                        feedRefreshInterval = setInterval(autoRefreshFeedTick, 5000);
                    }
                } else {
                    throw new Error('Failed to start check');
                }
            } catch (error) {
                showStatus('Failed to start video check', true);
                console.error(error);
            } finally {
                setTimeout(() => {
                    btn.disabled = false;
                    btn.textContent = originalText;
                }, 3000);
            }
        }

        // ============================================================================
        // SINGLE VIDEO ADDITION
        // ============================================================================

        /**
         * Add a single video manually via URL
         *
         * Process:
         * 1. Validate URL input
         * 2. Call backend API to add video
         * 3. Handle success (clear input, reload feed)
         * 4. Handle errors (show message)
         *
         * The video will be added to database with source_type='via_manual'
         * and processed in background (transcript -> AI summary -> email)
         */
        async function addSingleVideo() {
            const urlInput = document.getElementById('singleVideoUrl');
            const addBtn = document.getElementById('addSingleVideoBtn');
            const videoUrl = urlInput.value.trim();

            if (!videoUrl) {
                showSingleVideoStatus('Please enter a YouTube video URL', true);
                return;
            }

            // Disable button and show loading state
            addBtn.disabled = true;
            addBtn.textContent = 'Processing...';

            try {
                const response = await fetch('/api/videos/add-single', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        video_url: videoUrl
                    })
                });

                const result = await response.json();

                if (response.ok) {
                    // Success!
                    showSingleVideoStatus(`✅ ${result.message}`, false);

                    // Clear input
                    urlInput.value = '';

                    // Reload feed immediately to show the new video (it will be in "pending" state)
                    loadVideoFeed(true, true);

                    // Start periodic status updates if not already running
                    if (!feedRefreshInterval) {
                        feedRefreshInterval = setInterval(autoRefreshFeedTick, 5000);
                    }

                } else {
                    // Error from backend
                    showSingleVideoStatus(`❌ ${result.detail || 'Failed to add video'}`, true);
                }

            } catch (error) {
                console.error('Error adding single video:', error);
                showSingleVideoStatus('❌ Network error. Please try again.', true);
            } finally {
                // Re-enable button
                addBtn.disabled = false;
                addBtn.textContent = 'Process Video';
            }
        }

        /**
         * Show status message for single video addition
         *
         * @param {string} msg - Message to display
         * @param {boolean} isError - Whether this is an error message
         */
        function showSingleVideoStatus(msg, isError) {
            const status = document.getElementById('singleVideoStatus');
            if (!status) {
                console.warn('singleVideoStatus element not found');
                return;
            }
            status.textContent = msg;
            status.className = isError ? 'status error show' : 'status show';
            setTimeout(() => status.classList.remove('show'), isError ? 5000 : 3000);
        }

        // Keyboard shortcut for single video input
        document.getElementById('singleVideoUrl').addEventListener('keypress', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addSingleVideo();
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                closeModal();
                closeSummaryModal();
                closeLogsModal();
            }
        });

        // ============================================================================
        // IMPORT/EXPORT FUNCTIONS
        // ============================================================================

        // Global variable to store selected file for import
        let selectedImportFile = null;

        // Export Feed (JSON or CSV)
        async function exportFeed(format) {
            const btn = event.target.closest('button');
            const originalText = btn.innerHTML;

            try {
                btn.disabled = true;
                btn.innerHTML = '<div style="font-weight: bold;">Exporting...</div>';

                const response = await fetch(`/api/export/feed?format=${format}`);

                if (!response.ok) {
                    throw new Error(`Export failed: ${response.statusText}`);
                }

                // Trigger download
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;

                // Extract filename from Content-Disposition header
                const disposition = response.headers.get('Content-Disposition');
                const filenameMatch = disposition && disposition.match(/filename="(.+)"/);
                a.download = filenameMatch ? filenameMatch[1] : `yays_export.${format}`;

                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);

                showStatus(`Export successful! File downloaded: ${a.download}`, false);

            } catch (error) {
                console.error('Export error:', error);
                showStatus(`Export failed: ${error.message}`, true);
            } finally {
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }, 1000);
            }
        }

        // Export Complete Backup
        async function exportBackup() {
            const btn = event.target.closest('button');
            const originalText = btn.innerHTML;

            try {
                btn.disabled = true;
                btn.innerHTML = '<div style="font-weight: bold;">Exporting...</div>';

                const response = await fetch('/api/export/backup');

                if (!response.ok) {
                    throw new Error(`Export failed: ${response.statusText}`);
                }

                // Trigger download
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;

                const disposition = response.headers.get('Content-Disposition');
                const filenameMatch = disposition && disposition.match(/filename="(.+)"/);
                a.download = filenameMatch ? filenameMatch[1] : 'yays_full_backup.json';

                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);

                showStatus(`Backup successful! File downloaded: ${a.download}`, false);

            } catch (error) {
                console.error('Export error:', error);
                showStatus(`Export failed: ${error.message}`, true);
            } finally {
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }, 1000);
            }
        }

        // Setup drag-and-drop for import
        const dropzone = document.getElementById('importDropzone');

        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Highlight dropzone on drag over
        ['dragenter', 'dragover'].forEach(eventName => {
            dropzone.addEventListener(eventName, () => {
                dropzone.style.borderColor = 'rgba(255, 255, 255, 0.8)';
                dropzone.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, () => {
                dropzone.style.borderColor = 'rgba(255, 255, 255, 0.3)';
                dropzone.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
            }, false);
        });

        // Handle dropped files
        dropzone.addEventListener('drop', handleFileDrop, false);

        function handleFileDrop(e) {
            const dt = e.dataTransfer;
            const files = dt.files;

            if (files.length > 0) {
                handleFile(files[0]);
            }
        }

        // Handle file selection from file picker
        function handleFileSelect(e) {
            const files = e.target.files;
            if (files.length > 0) {
                handleFile(files[0]);
            }
        }

        // Handle file (common logic for drag-and-drop and file picker)
        async function handleFile(file) {
            // Check file type
            if (!file.name.endsWith('.json')) {
                showStatus('Invalid file type. Please select a JSON file.', true);
                return;
            }

            // Store file
            selectedImportFile = file;

            // Update UI - show filename
            document.getElementById('dropzoneDefault').style.display = 'none';
            document.getElementById('dropzoneFile').style.display = 'block';
            document.getElementById('dropzoneFileName').textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
            document.getElementById('dropzoneValidating').textContent = 'Validating...';
            document.getElementById('dropzoneValidating').style.color = '#888';

            // Show import buttons container
            document.getElementById('importButtonsContainer').style.display = 'flex';

            // Validate file
            await validateImportFile(file);
        }

        // Validate import file
        async function validateImportFile(file) {
            try {
                // Create FormData
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch('/api/import/validate', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.valid) {
                    // Show success
                    document.getElementById('dropzoneValidating').textContent = '✓ Valid file, ready to import';
                    document.getElementById('dropzoneValidating').style.color = '#4ade80';

                    // Show preview
                    renderValidationPreview(result);

                    // Enable import button
                    document.getElementById('importButton').disabled = false;
                    document.getElementById('importButton').style.backgroundColor = '#16a34a';

                } else {
                    // Show error
                    document.getElementById('dropzoneValidating').textContent = '✗ Validation failed';
                    document.getElementById('dropzoneValidating').style.color = '#ef4444';

                    // Show errors
                    renderValidationErrors(result);

                    // Disable import button
                    document.getElementById('importButton').disabled = true;
                    document.getElementById('importButton').style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
                }

            } catch (error) {
                console.error('Validation error:', error);
                document.getElementById('dropzoneValidating').textContent = '✗ Validation error';
                document.getElementById('dropzoneValidating').style.color = '#ef4444';
                showStatus(`Validation failed: ${error.message}`, true);
            }
        }

        // Render validation preview (success)
        function renderValidationPreview(result) {
            const preview = result.preview;
            const previewDiv = document.getElementById('validationPreview');
            const contentDiv = document.getElementById('validationContent');

            let html = '<div style="color: #4ade80; margin-bottom: 8px;">✓ Valid file format</div>';

            if (result.warnings.length > 0) {
                html += '<div style="color: #fbbf24; margin-bottom: 8px;">';
                result.warnings.forEach(warning => {
                    html += `⚠ ${warning}<br>`;
                });
                html += '</div>';
            }

            html += '<div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1);">';
            html += '<div style="font-weight: bold; margin-bottom: 8px;">Changes to apply:</div>';
            html += `<div>• Channels: Add ${preview.channels_new} new (${preview.channels_existing} existing)</div>`;
            html += `<div>• Videos: Add ${preview.videos_new} new (${preview.videos_duplicate} skipped)</div>`;

            if (preview.settings_changed > 0) {
                html += `<div>• Settings: Replace ${preview.settings_changed} values</div>`;
                if (preview.settings_details.length > 0) {
                    html += '<div style="font-size: 12px; color: #888; margin-left: 16px; margin-top: 4px;">';
                    preview.settings_details.forEach(detail => {
                        html += `${detail}<br>`;
                    });
                    html += '</div>';
                }
            } else {
                html += '<div>• Settings: No changes</div>';
            }

            html += `<div style="margin-top: 8px; font-size: 12px; color: #888;">Total size: ${preview.total_size_mb} MB</div>`;
            html += '</div>';

            contentDiv.innerHTML = html;
            previewDiv.style.display = 'block';
        }

        // Render validation errors
        function renderValidationErrors(result) {
            const previewDiv = document.getElementById('validationPreview');
            const contentDiv = document.getElementById('validationContent');

            let html = '<div style="color: #ef4444; margin-bottom: 12px; font-weight: bold;">Validation Failed</div>';
            html += '<div style="border-top: 1px solid rgba(255,255,255,0.1); padding-top: 12px;">';

            if (result.errors.length > 0) {
                result.errors.forEach(error => {
                    html += `<div style="color: #ef4444; margin-bottom: 4px;">✗ ${error}</div>`;
                });
            }

            if (result.warnings.length > 0) {
                html += '<div style="margin-top: 12px;">';
                result.warnings.forEach(warning => {
                    html += `<div style="color: #fbbf24; margin-bottom: 4px;">⚠ ${warning}</div>`;
                });
                html += '</div>';
            }

            html += '<div style="margin-top: 12px; color: #888;">Please fix errors and try again.</div>';
            html += '</div>';

            contentDiv.innerHTML = html;
            previewDiv.style.display = 'block';
        }

        // Execute import
        async function executeImport() {
            if (!selectedImportFile) {
                showStatus('No file selected', true);
                return;
            }

            const btn = document.getElementById('importButton');
            const originalText = btn.textContent;

            try {
                btn.disabled = true;
                btn.textContent = 'Importing...';

                // Create FormData
                const formData = new FormData();
                formData.append('file', selectedImportFile);

                const response = await fetch('/api/import/execute', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (result.success) {
                    const message = `Import successful! Added ${result.channels_added} channels, ${result.videos_added} videos, updated ${result.settings_updated} settings.`;
                    showStatus(message, false);

                    // Reset import UI
                    cancelImport();

                    // Refresh data
                    await loadChannels();
                    await refreshFeed();

                    // Refresh settings to show updated values immediately
                    if (result.settings_updated > 0) {
                        await loadSettings();
                        await loadPrompt();  // Refresh AI prompt template if updated
                    }

                } else {
                    const errors = result.errors.join('; ');
                    showStatus(`Import failed: ${errors}`, true);
                }

            } catch (error) {
                console.error('Import error:', error);
                showStatus(`Import failed: ${error.message}`, true);
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        // Cancel import
        function cancelImport() {
            selectedImportFile = null;

            // Reset dropzone
            document.getElementById('dropzoneDefault').style.display = 'block';
            document.getElementById('dropzoneFile').style.display = 'none';

            // Hide preview
            document.getElementById('validationPreview').style.display = 'none';

            // Hide import buttons container
            document.getElementById('importButtonsContainer').style.display = 'none';

            // Disable import button
            document.getElementById('importButton').disabled = true;
            document.getElementById('importButton').style.backgroundColor = 'rgba(255, 255, 255, 0.1)';

            // Clear file input
            document.getElementById('importFileInput').value = '';
        }

        // ============================================================================
        // TABLE OF CONTENTS (TOC) NAVIGATION
        // ============================================================================

        // Global state for TOC
        let tocObserver = null;
        let currentActiveSection = null;

        // Generate TOC for the current active tab
        function generateTOC() {
            // Find the currently active tab
            const activeTab = document.querySelector('.tab-content.active');
            if (!activeTab) {
                hideTOC();
                return;
            }

            // Find all h3 elements within .settings-section
            const sections = activeTab.querySelectorAll('.settings-section h3');

            // Apply threshold: only show TOC if 2 or more sections exist
            if (sections.length < 2) {
                hideTOC();
                return;
            }

            // Extract section data
            const tocItems = [];
            sections.forEach((heading, index) => {
                // Clone heading and remove unsaved indicators
                const clone = heading.cloneNode(true);
                const unsavedIndicators = clone.querySelectorAll('.unsaved-indicator');
                unsavedIndicators.forEach(indicator => indicator.remove());

                // Extract text and remove emojis
                const rawText = clone.textContent || clone.innerText;
                const text = rawText.replace(/[\u{1F300}-\u{1F9FF}]/gu, '').replace(/[^\x00-\x7F]/g, '').trim();

                // Generate unique ID
                const baseId = text.toLowerCase()
                    .replace(/\s+/g, '-')
                    .replace(/[^a-z0-9-]/g, '')
                    .replace(/-+/g, '-')
                    .replace(/^-|-$/g, '');

                // Handle empty or duplicate IDs
                const id = baseId || `section-${index}`;
                const uniqueId = `section-${id}`;

                // Add ID to the section's parent (.settings-section)
                const section = heading.closest('.settings-section');
                if (section) {
                    section.id = uniqueId;
                }

                tocItems.push({ id: uniqueId, text: text || `Section ${index + 1}` });
            });

            // Render TOC
            renderTOC(tocItems);

            // Initialize scroll-spy
            initScrollSpy();

            // Show TOC
            showTOC();
        }

        // Render TOC HTML for both desktop and mobile
        function renderTOC(items) {
            // Render desktop TOC
            const tocList = document.getElementById('tocList');
            tocList.innerHTML = '';

            items.forEach((item, index) => {
                const li = document.createElement('li');
                li.className = 'toc-item';
                if (index === 0) li.classList.add('active'); // First item active by default

                const link = document.createElement('a');
                link.href = `#${item.id}`;
                link.className = 'toc-link';
                link.textContent = item.text;
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    scrollToSection(item.id);
                });

                li.appendChild(link);
                tocList.appendChild(li);
            });

            // Render mobile TOC (same structure)
            const tocListMobile = document.getElementById('tocListMobile');
            tocListMobile.innerHTML = '';

            items.forEach((item, index) => {
                const li = document.createElement('li');
                li.className = 'toc-item';
                if (index === 0) li.classList.add('active');

                const link = document.createElement('a');
                link.href = `#${item.id}`;
                link.className = 'toc-link';
                link.textContent = item.text;
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    scrollToSection(item.id);
                    closeMobileTOC(); // Close drawer after navigation
                });

                li.appendChild(link);
                tocListMobile.appendChild(li);
            });
        }

        // Initialize scroll-spy with Intersection Observer
        function initScrollSpy() {
            // Clean up existing observer
            if (tocObserver) {
                tocObserver.disconnect();
            }

            // Find all sections with IDs starting with "section-"
            const sections = document.querySelectorAll('.settings-section[id^="section-"]');

            if (sections.length === 0) return;

            // Create Intersection Observer
            tocObserver = new IntersectionObserver(
                (entries) => {
                    entries.forEach(entry => {
                        if (entry.isIntersecting && entry.intersectionRatio > 0) {
                            setActiveSection(entry.target.id);
                        }
                    });
                },
                {
                    root: null, // viewport
                    rootMargin: '-20% 0px -75% 0px', // Top 20% of viewport
                    threshold: 0
                }
            );

            // Observe all sections
            sections.forEach(section => {
                tocObserver.observe(section);
            });
        }

        // Set active section in TOC
        function setActiveSection(sectionId) {
            if (currentActiveSection === sectionId) return;
            currentActiveSection = sectionId;

            // Update desktop TOC
            document.querySelectorAll('#tocList .toc-item').forEach(item => {
                item.classList.remove('active');
            });

            const activeLink = document.querySelector(`#tocList .toc-link[href="#${sectionId}"]`);
            if (activeLink) {
                activeLink.closest('.toc-item').classList.add('active');
            }

            // Update mobile TOC
            document.querySelectorAll('#tocListMobile .toc-item').forEach(item => {
                item.classList.remove('active');
            });

            const activeLinkMobile = document.querySelector(`#tocListMobile .toc-link[href="#${sectionId}"]`);
            if (activeLinkMobile) {
                activeLinkMobile.closest('.toc-item').classList.add('active');
            }
        }

        // Scroll to section (instant, no smooth animation)
        function scrollToSection(sectionId) {
            const section = document.getElementById(sectionId);
            if (!section) return;

            // Instant scroll
            section.scrollIntoView({
                behavior: 'auto',
                block: 'start'
            });

            // Update active state immediately
            setActiveSection(sectionId);
        }

        // Show TOC
        function showTOC() {
            const tocContainer = document.getElementById('tocContainer');
            tocContainer.classList.add('show');
            document.getElementById('tocToggle').classList.add('show');

            // Dynamically position TOC to align with first section
            const activeTab = document.querySelector('.tab-content.active');
            if (activeTab) {
                const firstSection = activeTab.querySelector('.settings-section');
                if (firstSection) {
                    const rect = firstSection.getBoundingClientRect();
                    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                    const absoluteTop = rect.top + scrollTop;
                    tocContainer.style.top = `${rect.top}px`;
                }
            }
        }

        // Hide TOC
        function hideTOC() {
            document.getElementById('tocContainer').classList.remove('show');
            document.getElementById('tocToggle').classList.remove('show');

            // Clean up observer
            if (tocObserver) {
                tocObserver.disconnect();
                tocObserver = null;
            }

            // Reset state
            currentActiveSection = null;
        }

        // Mobile TOC toggle handlers
        function openMobileTOC() {
            document.getElementById('tocDrawer').classList.add('open');
            document.getElementById('tocBackdrop').classList.add('show');
        }

        function closeMobileTOC() {
            document.getElementById('tocDrawer').classList.remove('open');
            document.getElementById('tocBackdrop').classList.remove('show');
        }

        // Event listeners for mobile TOC
        document.getElementById('tocToggle').addEventListener('click', openMobileTOC);
        document.getElementById('tocDrawerClose').addEventListener('click', closeMobileTOC);
        document.getElementById('tocBackdrop').addEventListener('click', closeMobileTOC);

        // Close mobile TOC on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeMobileTOC();
            }
        });

        // ============================================================================
        // LOGS TAB
        // ============================================================================

        // Global state
        let currentLogSource = 'summarizer';
        let logsAutoRefreshInterval = null;
        let currentRawLogContent = '';

        // Load logs tab
        async function loadLogsTab() {
            await loadLogs(currentLogSource);
        }

        // Load logs from API
        async function loadLogs(logName) {
            const viewer = document.getElementById('logViewer');
            const info = document.getElementById('logInfo');

            if (!viewer || !info) return;

            try {
                viewer.innerHTML = '<div class="log-loading">Loading logs...</div>';

                const response = await fetch(`/api/logs/${logName}?lines=1000`);
                if (!response.ok) {
                    throw new Error('Failed to load logs');
                }

                const data = await response.json();
                currentRawLogContent = data.content;

                // Update info
                const sizeKB = (data.file_size_bytes / 1024).toFixed(1);
                info.textContent = `Showing ${data.returned_lines} of ${data.total_lines} lines (${sizeKB} KB)`;

                // Display logs with filters applied
                applyLogFilters();

                // Auto-scroll to bottom
                viewer.scrollTop = viewer.scrollHeight;

            } catch (error) {
                viewer.innerHTML = '<div class="log-empty">Failed to load logs</div>';
                showStatus('Failed to load logs', true);
                console.error(error);
            }
        }

        // Toggle between web/summarizer logs
        function toggleLogSource(logName) {
            currentLogSource = logName;

            // Update toggle buttons
            document.querySelectorAll('.log-toggle-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.log === logName);
            });

            loadLogs(logName);
        }

        // Apply filters and search
        function applyLogFilters() {
            const viewer = document.getElementById('logViewer');
            const levelFilter = document.getElementById('logLevelFilter').value;
            const searchQuery = document.getElementById('logSearch').value.trim().toLowerCase();

            if (!currentRawLogContent) {
                viewer.innerHTML = '<div class="log-empty">No logs available</div>';
                return;
            }

            let lines = currentRawLogContent.split('\n');

            // Filter by level
            if (levelFilter !== 'all') {
                const pattern = new RegExp(`\\[${levelFilter}\\]`, 'i');
                lines = lines.filter(line => pattern.test(line));
            }

            // Filter by search
            if (searchQuery) {
                lines = lines.filter(line => line.toLowerCase().includes(searchQuery));
            }

            // Update display
            if (lines.length === 0) {
                viewer.innerHTML = '<div class="log-empty">No matching log lines</div>';
            } else {
                viewer.textContent = lines.join('\n');
            }

            // Update info
            const info = document.getElementById('logInfo');
            if (info) {
                const totalLines = currentRawLogContent.split('\n').length;
                info.textContent = `Showing ${lines.length} of ${totalLines} lines`;
            }
        }

        // Clear search
        function clearLogSearch() {
            document.getElementById('logSearch').value = '';
            applyLogFilters();
        }

        // Copy all logs to clipboard
        async function copyAllLogs() {
            if (!currentRawLogContent) {
                showStatus('No logs available to copy', 'error');
                return;
            }

            try {
                await navigator.clipboard.writeText(currentRawLogContent);
                showStatus('Logs copied to clipboard!', 'success');
            } catch (err) {
                console.error('Failed to copy logs:', err);
                showStatus('Failed to copy logs to clipboard', 'error');
            }
        }

        // Download logs
        async function downloadLogs() {
            const url = `/api/logs/${currentLogSource}/download`;
            window.open(url, '_blank');
        }

        // Manual refresh logs
        function manualRefreshLogs() {
            loadLogs(currentLogSource);
        }

        // Toggle auto-refresh
        function toggleAutoRefresh() {
            const btn = document.getElementById('autoRefreshBtn');

            if (logsAutoRefreshInterval) {
                // Disable
                clearInterval(logsAutoRefreshInterval);
                logsAutoRefreshInterval = null;
                btn.textContent = 'Auto-refresh: OFF';
                btn.classList.remove('active');
            } else {
                // Enable
                logsAutoRefreshInterval = setInterval(() => {
                    loadLogs(currentLogSource);
                }, 5000);
                btn.textContent = 'Auto-refresh: ON';
                btn.classList.add('active');
            }
        }
