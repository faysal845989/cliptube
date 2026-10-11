let ytPlayer = null;
let currentVideoData = null;
let currentMode = 'single'; // 'single' or 'batch'
let currentSource = 'youtube'; // 'youtube' or 'upload'
let activeLocalFile = null;

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    loadClipsLibrary();
});

function extractVideoId(url) {
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|\&v=)([^#\&\?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
}

function parseSeconds(timeStr) {
    if (!timeStr) return 0;
    const parts = timeStr.trim().split(':');
    if (parts.length === 3) {
        return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
    } else if (parts.length === 2) {
        return parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
    }
    return parseFloat(parts[0]) || 0;
}

function formatSeconds(totalSeconds) {
    totalSeconds = Math.max(0, Math.floor(totalSeconds));
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    if (h > 0) {
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function initEventListeners() {
    const videoUrlInput = document.getElementById('video-url');
    const btnPaste = document.getElementById('btn-paste');
    const btnLoad = document.getElementById('btn-load');

    // Source Selector Tabs
    const sourceTabYt = document.getElementById('source-tab-yt');
    const sourceTabUpload = document.getElementById('source-tab-upload');
    const ytInputWrapper = document.getElementById('yt-input-wrapper');
    const uploadInputWrapper = document.getElementById('upload-input-wrapper');

    sourceTabYt.addEventListener('click', () => {
        currentSource = 'youtube';
        sourceTabYt.classList.add('active');
        sourceTabUpload.classList.remove('active');
        ytInputWrapper.classList.remove('hidden');
        uploadInputWrapper.classList.add('hidden');
    });

    sourceTabUpload.addEventListener('click', () => {
        currentSource = 'upload';
        sourceTabUpload.classList.add('active');
        sourceTabYt.classList.remove('active');
        uploadInputWrapper.classList.remove('hidden');
        ytInputWrapper.classList.add('hidden');
    });

    // File Upload Handlers
    const fileInput = document.getElementById('local-file-input');
    const dropzone = document.getElementById('upload-input-wrapper');
    const btnTriggerUpload = document.getElementById('btn-trigger-upload');

    btnTriggerUpload.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            uploadLocalVideo(e.target.files[0]);
        }
    });

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            uploadLocalVideo(e.dataTransfer.files[0]);
        }
    });

    // Mode tab switching
    const tabSingle = document.getElementById('tab-single');
    const tabBatch = document.getElementById('tab-batch');
    const singleContainer = document.getElementById('mode-single-container');
    const batchContainer = document.getElementById('mode-batch-container');

    tabSingle.addEventListener('click', () => {
        currentMode = 'single';
        tabSingle.classList.add('active');
        tabBatch.classList.remove('active');
        singleContainer.classList.remove('hidden');
        batchContainer.classList.add('hidden');
    });

    tabBatch.addEventListener('click', () => {
        currentMode = 'batch';
        tabBatch.classList.add('active');
        tabSingle.classList.remove('active');
        batchContainer.classList.remove('hidden');
        singleContainer.classList.add('hidden');
        updateBatchPreview();
    });

    document.getElementById('batch-interval-select').addEventListener('change', updateBatchPreview);

    // Clipboard paste button
    btnPaste.addEventListener('click', async () => {
        try {
            const text = await navigator.clipboard.readText();
            videoUrlInput.value = text;
            if (text.trim()) loadVideoMetadata(text.trim());
        } catch (err) {
            console.error("Clipboard permission error", err);
        }
    });

    videoUrlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            loadVideoMetadata(videoUrlInput.value.trim());
        }
    });

    btnLoad.addEventListener('click', () => {
        loadVideoMetadata(videoUrlInput.value.trim());
    });

    // Set timestamps from current player position
    document.getElementById('btn-set-start').addEventListener('click', () => {
        let currentTime = 0;
        if (currentSource === 'upload') {
            const localPlayer = document.getElementById('local-player');
            currentTime = localPlayer.currentTime || 0;
        } else if (ytPlayer && ytPlayer.getCurrentTime) {
            currentTime = ytPlayer.getCurrentTime();
        }
        document.getElementById('start-time').value = formatSeconds(currentTime);
        updateDurationDisplay();
    });

    document.getElementById('btn-set-end').addEventListener('click', () => {
        let currentTime = 0;
        if (currentSource === 'upload') {
            const localPlayer = document.getElementById('local-player');
            currentTime = localPlayer.currentTime || 0;
        } else if (ytPlayer && ytPlayer.getCurrentTime) {
            currentTime = ytPlayer.getCurrentTime();
        }
        document.getElementById('end-time').value = formatSeconds(currentTime);
        updateDurationDisplay();
    });

    document.getElementById('start-time').addEventListener('input', updateDurationDisplay);
    document.getElementById('end-time').addEventListener('input', updateDurationDisplay);

    document.querySelectorAll('.btn-preset').forEach(btn => {
        btn.addEventListener('click', () => {
            const secs = parseFloat(btn.dataset.secs);
            const startSecs = parseSeconds(document.getElementById('start-time').value);
            document.getElementById('end-time').value = formatSeconds(startSecs + secs);
            updateDurationDisplay();
        });
    });

    document.getElementById('btn-create-clip').addEventListener('click', handleCreateClip);

    document.getElementById('btn-close-result').addEventListener('click', () => {
        document.getElementById('result-modal').classList.add('hidden');
    });

    document.getElementById('btn-refresh-library').addEventListener('click', loadClipsLibrary);

    const btnClearAll = document.getElementById('btn-clear-all');
    if (btnClearAll) {
        btnClearAll.addEventListener('click', handleClearAllStorage);
    }

    document.getElementById('btn-copy-link').addEventListener('click', () => {
        const downloadBtn = document.getElementById('btn-download-clip');
        navigator.clipboard.writeText(downloadBtn.href);
        alert('Direct download link copied to clipboard!');
    });
}

function updateDurationDisplay() {
    const start = parseSeconds(document.getElementById('start-time').value);
    const end = parseSeconds(document.getElementById('end-time').value);
    const diff = Math.max(0, end - start);
    document.getElementById('clip-duration-text').textContent = formatSeconds(diff);
}

function updateBatchPreview() {
    if (!currentVideoData || !currentVideoData.duration) return;
    
    const duration = currentVideoData.duration;
    const intervalSecs = parseFloat(document.getElementById('batch-interval-select').value);
    
    const count = Math.ceil(duration / intervalSecs);
    const remainderSecs = duration % intervalSecs;
    
    document.getElementById('batch-parts-count').textContent = `${count} Parts`;
    document.getElementById('batch-parts-summary').textContent = `Part 1 to Part ${count}`;
    
    const noteEl = document.getElementById('batch-remainder-note');
    if (remainderSecs > 0 && count > 1) {
        noteEl.textContent = `Part 1 to Part ${count - 1} will be ${formatSeconds(intervalSecs)} long, and Part ${count} (final clip) will be ${formatSeconds(remainderSecs)} long.`;
    } else {
        noteEl.textContent = `All ${count} parts will be exactly ${formatSeconds(intervalSecs)} long.`;
    }
}

async function uploadLocalVideo(file) {
    const infoLoader = document.getElementById('info-loader');
    const workspace = document.getElementById('workspace');

    showError('');
    infoLoader.querySelector('p').textContent = `Uploading ${file.name}...`;
    infoLoader.classList.remove('hidden');
    workspace.classList.add('hidden');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        infoLoader.classList.add('hidden');

        if (!result.success) {
            showError(result.error || "Failed to upload video file.");
            return;
        }

        currentVideoData = result.data;
        activeLocalFile = result.data.filepath;
        renderWorkspaceLocal(currentVideoData);
    } catch (err) {
        infoLoader.classList.add('hidden');
        showError("Upload failed due to network or file size.");
        console.error(err);
    }
}

async function loadVideoMetadata(url) {
    const errorBanner = document.getElementById('url-error');
    const infoLoader = document.getElementById('info-loader');
    const workspace = document.getElementById('workspace');

    errorBanner.classList.add('hidden');

    if (!url) {
        showError("Please enter a valid YouTube video URL.");
        return;
    }

    const videoId = extractVideoId(url);
    if (!videoId) {
        showError("Could not parse YouTube video ID from URL.");
        return;
    }

    infoLoader.querySelector('p').textContent = "Fetching video details...";
    infoLoader.classList.remove('hidden');
    workspace.classList.add('hidden');
    activeLocalFile = null;

    try {
        const response = await fetch('/api/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const result = await response.json();
        infoLoader.classList.add('hidden');

        if (!result.success) {
            showError(result.error || "Failed to fetch video details.");
            return;
        }

        currentVideoData = result.data;
        renderWorkspaceYouTube(currentVideoData, videoId);
    } catch (err) {
        infoLoader.classList.add('hidden');
        showError("Network error while connecting to server.");
        console.error(err);
    }
}

function showError(msg) {
    const errorBanner = document.getElementById('url-error');
    const errorText = document.getElementById('error-text');
    if (!msg) {
        errorBanner.classList.add('hidden');
        return;
    }
    errorText.textContent = msg;
    errorBanner.classList.remove('hidden');
}

function renderWorkspaceYouTube(data, videoId) {
    document.getElementById('video-title').textContent = data.title;
    document.getElementById('video-channel').innerHTML = `<i class="fa-regular fa-user"></i> ${data.channel}`;
    document.getElementById('video-duration').innerHTML = `<i class="fa-regular fa-clock"></i> ${data.duration_formatted}`;

    const ytPlayerContainer = document.getElementById('youtube-player');
    const localPlayer = document.getElementById('local-player');

    localPlayer.classList.add('hidden');
    ytPlayerContainer.style.display = 'block';

    if (ytPlayer) {
        ytPlayer.loadVideoById(videoId);
    } else {
        ytPlayer = new YT.Player('youtube-player', {
            videoId: videoId,
            playerVars: { 'autoplay': 0, 'modestbranding': 1, 'rel': 0 }
        });
    }

    document.getElementById('start-time').value = "00:00";
    const defaultEnd = Math.min(15, data.duration || 15);
    document.getElementById('end-time').value = formatSeconds(defaultEnd);
    updateDurationDisplay();
    updateBatchPreview();

    // Render Chapters
    const chaptersContainer = document.getElementById('chapters-container');
    const chaptersList = document.getElementById('chapters-list');
    chaptersList.innerHTML = '';

    if (data.chapters && data.chapters.length > 0) {
        chaptersContainer.classList.remove('hidden');
        data.chapters.forEach(ch => {
            const chip = document.createElement('div');
            chip.className = 'chapter-chip';
            chip.innerHTML = `<i class="fa-solid fa-bookmark"></i> ${ch.title} (${ch.start_formatted} - ${ch.end_formatted})`;
            chip.addEventListener('click', () => {
                document.getElementById('start-time').value = ch.start_formatted;
                document.getElementById('end-time').value = ch.end_formatted;
                updateDurationDisplay();
                if (ytPlayer && ytPlayer.seekTo) {
                    ytPlayer.seekTo(ch.start_time, true);
                }
            });
            chaptersList.appendChild(chip);
        });
    } else {
        chaptersContainer.classList.add('hidden');
    }

    document.getElementById('workspace').classList.remove('hidden');
}

function renderWorkspaceLocal(data) {
    document.getElementById('video-title').textContent = data.title;
    document.getElementById('video-channel').innerHTML = `<i class="fa-solid fa-hard-drive"></i> Local Computer File`;
    document.getElementById('video-duration').innerHTML = `<i class="fa-regular fa-clock"></i> ${data.duration_formatted}`;

    const ytPlayerContainer = document.getElementById('youtube-player');
    const localPlayer = document.getElementById('local-player');

    ytPlayerContainer.style.display = 'none';
    localPlayer.src = data.url;
    localPlayer.classList.remove('hidden');

    document.getElementById('start-time').value = "00:00";
    const defaultEnd = Math.min(15, data.duration || 15);
    document.getElementById('end-time').value = formatSeconds(defaultEnd);
    updateDurationDisplay();
    updateBatchPreview();

    document.getElementById('chapters-container').classList.add('hidden');
    document.getElementById('workspace').classList.remove('hidden');
}

async function handleCreateClip() {
    if (!currentVideoData) return;

    const exportFormat = document.querySelector('input[name="export_format"]:checked').value;
    const aspectRatio = document.querySelector('input[name="aspect_ratio"]:checked').value;
    const processingModal = document.getElementById('processing-modal');

    const requestPayload = {
        format: exportFormat,
        aspect_ratio: aspectRatio
    };

    if (activeLocalFile) {
        requestPayload.filepath = activeLocalFile;
    } else {
        requestPayload.url = currentVideoData.url;
    }

    if (currentMode === 'batch') {
        const intervalSecs = parseFloat(document.getElementById('batch-interval-select').value);
        requestPayload.interval_seconds = intervalSecs;

        document.getElementById('processing-status-text').textContent = `Cutting video into ${intervalSecs}s parts (Part 1, Part 2...) in sub-second speed...`;
        processingModal.classList.remove('hidden');

        try {
            const response = await fetch('/api/batch-clip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestPayload)
            });

            const result = await response.json();
            processingModal.classList.add('hidden');

            if (!result.success) {
                alert("Error creating batch clips: " + (result.error || "Unknown error"));
                return;
            }

            showBatchResultModal(result.batch);
            loadClipsLibrary();
        } catch (err) {
            processingModal.classList.add('hidden');
            alert("Network error while creating batch clips.");
            console.error(err);
        }
    } else {
        const startTime = document.getElementById('start-time').value;
        const endTime = document.getElementById('end-time').value;

        const startSec = parseSeconds(startTime);
        const endSec = parseSeconds(endTime);

        if (endSec <= startSec) {
            alert("End time must be greater than start time.");
            return;
        }

        requestPayload.start_time = startTime;
        requestPayload.end_time = endTime;

        document.getElementById('processing-status-text').textContent = "Performing sub-second instant video cut...";
        processingModal.classList.remove('hidden');

        try {
            const response = await fetch('/api/clip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestPayload)
            });

            const result = await response.json();
            processingModal.classList.add('hidden');

            if (!result.success) {
                alert("Error creating clip: " + (result.error || "Unknown error"));
                return;
            }

            showSingleResultModal(result.clip);
            loadClipsLibrary();
        } catch (err) {
            processingModal.classList.add('hidden');
            alert("Network error while creating clip.");
            console.error(err);
        }
    }
}

function showSingleResultModal(clip) {
    const resultModal = document.getElementById('result-modal');
    document.getElementById('result-modal-title').textContent = "Your Clip is Ready!";

    document.getElementById('single-result-view').classList.remove('hidden');
    document.getElementById('batch-result-view').classList.add('hidden');

    const downloadBtn = document.getElementById('btn-download-clip');
    const fileSizeSpan = document.getElementById('result-file-size');

    const videoEl = document.getElementById('clip-preview-video');
    const audioEl = document.getElementById('clip-preview-audio');
    const gifEl = document.getElementById('clip-preview-gif');

    videoEl.classList.add('hidden');
    audioEl.classList.add('hidden');
    gifEl.classList.add('hidden');

    const fileUrl = `/api/download/${clip.filename}`;
    const previewUrl = `/static/exports/${clip.filename}`;

    downloadBtn.href = fileUrl;
    downloadBtn.setAttribute('download', clip.filename);
    fileSizeSpan.textContent = clip.size_mb || '--';

    if (clip.format === 'mp3') {
        audioEl.src = previewUrl;
        audioEl.classList.remove('hidden');
    } else if (clip.format === 'gif') {
        gifEl.src = previewUrl;
        gifEl.classList.remove('hidden');
    } else {
        videoEl.src = previewUrl;
        videoEl.classList.remove('hidden');
        videoEl.play();
    }

    resultModal.classList.remove('hidden');
}

function showBatchResultModal(batch) {
    const resultModal = document.getElementById('result-modal');
    document.getElementById('result-modal-title').textContent = `Batch Split Complete! (${batch.parts_count} Parts)`;

    document.getElementById('single-result-view').classList.add('hidden');
    document.getElementById('batch-result-view').classList.remove('hidden');

    const downloadZipBtn = document.getElementById('btn-download-zip');
    if (batch.zip_download_url) {
        downloadZipBtn.href = batch.zip_download_url;
        downloadZipBtn.style.display = 'inline-flex';
    } else {
        downloadZipBtn.style.display = 'none';
    }

    document.getElementById('parts-total-count').textContent = batch.parts_count;

    const partsListContainer = document.getElementById('batch-parts-list');
    partsListContainer.innerHTML = '';

    batch.parts.forEach(part => {
        const item = document.createElement('div');
        item.className = 'batch-part-item';
        item.innerHTML = `
            <div class="part-info">
                <div class="part-title"><i class="fa-solid fa-play text-green"></i> ${part.title} (${part.duration_formatted})</div>
                <div class="part-timing">Timing: ${part.start_time} - ${part.end_time}</div>
            </div>
            <a href="${part.download_url}" download class="btn-primary btn-sm">
                <i class="fa-solid fa-download"></i> Download ${part.title}
            </a>
        `;
        partsListContainer.appendChild(item);
    });

    resultModal.classList.remove('hidden');
}

async function loadClipsLibrary() {
    const clipsGrid = document.getElementById('clips-grid');
    
    // Fetch storage info
    try {
        const storageRes = await fetch('/api/storage-info');
        const storageData = await storageRes.json();
        const mbEl = document.getElementById('storage-mb');
        const filesEl = document.getElementById('storage-files');
        if (mbEl) mbEl.textContent = storageData.size_mb || '0';
        if (filesEl) filesEl.textContent = storageData.file_count || '0';
    } catch (e) {
        console.error("Storage info error", e);
    }

    try {
        const response = await fetch('/api/clips');
        const result = await response.json();

        if (!result.success || !result.clips || result.clips.length === 0) {
            clipsGrid.innerHTML = '<p class="empty-state">No clips created yet. Paste a YouTube link or upload a file above to create your first clip!</p>';
            return;
        }

        clipsGrid.innerHTML = '';
        result.clips.forEach(clip => {
            const isZip = clip.filename.includes('.zip');
            const card = document.createElement('div');
            card.className = 'clip-card';
            card.innerHTML = `
                <div class="clip-card-header">
                    <span class="clip-card-title">${isZip ? '<i class="fa-solid fa-file-zipper"></i> ' : '<i class="fa-solid fa-file-video"></i> '}${clip.filename}</span>
                </div>
                <div class="clip-card-meta">
                    <span><i class="fa-solid fa-hard-drive"></i> ${clip.size_mb} MB</span>
                    <span><i class="fa-regular fa-clock"></i> ${new Date(clip.mtime * 1000).toLocaleTimeString()}</span>
                </div>
                <div class="clip-card-actions">
                    <a href="${clip.download_url}" download class="btn-primary btn-sm" style="flex:1; text-align:center;">
                        <i class="fa-solid fa-download"></i> Download
                    </a>
                    <button class="btn-danger-sm" onclick="deleteClip('${clip.filename}')" title="Delete this clip">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            `;
            clipsGrid.appendChild(card);
        });
    } catch (err) {
        console.error("Failed to load clips library", err);
    }
}

async function handleClearAllStorage() {
    if (!confirm("Are you sure you want to clear all storage? This will delete all generated clips, cache, and uploaded files to instantly free up disk space.")) {
        return;
    }
    try {
        const response = await fetch('/api/clips/clear-all', { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            alert(`Storage cleared! Deleted ${result.deleted} files and freed ${result.freed_mb} MB of disk space.`);
            loadClipsLibrary();
        } else {
            alert("Could not clear storage.");
        }
    } catch (err) {
        console.error(err);
        alert("Failed to clear storage.");
    }
}

async function deleteClip(filename) {
    if (!confirm(`Delete ${filename}?`)) return;
    try {
        const response = await fetch(`/api/clips/${filename}`, { method: 'DELETE' });
        const result = await response.json();
        if (result.success) {
            loadClipsLibrary();
        } else {
            alert(result.error || "Failed to delete clip");
        }
    } catch (err) {
        console.error(err);
    }
}

