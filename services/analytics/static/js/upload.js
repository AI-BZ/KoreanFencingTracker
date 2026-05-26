/**
 * FencingMind Analytics - Upload functionality
 * Handles drag-and-drop, file validation, XHR upload with progress.
 */
(function () {
    'use strict';

    const MAX_SIZE_MB = 500;
    const ALLOWED_TYPES = ['video/mp4', 'video/x-msvideo', 'video/quicktime'];
    const ALLOWED_EXTENSIONS = ['.mp4', '.avi', '.mov'];

    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const dropZoneContent = document.getElementById('drop-zone-content');
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const fileSize = document.getElementById('file-size');
    const removeFileBtn = document.getElementById('remove-file');
    const progressSection = document.getElementById('progress-section');
    const progressBar = document.getElementById('progress-bar');
    const progressPct = document.getElementById('progress-pct');
    const uploadBtn = document.getElementById('upload-btn');
    const uploadForm = document.getElementById('upload-form');
    const uploadSuccess = document.getElementById('upload-success');

    let selectedFile = null;

    // -- Drag & Drop --

    dropZone.addEventListener('click', function () {
        if (!selectedFile) fileInput.click();
    });

    dropZone.addEventListener('dragover', function (e) {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', function () {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', function (e) {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', function () {
        if (fileInput.files.length > 0) {
            handleFile(fileInput.files[0]);
        }
    });

    removeFileBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        clearFile();
    });

    // -- File Handling --

    function handleFile(file) {
        // Validate extension
        var ext = '.' + file.name.split('.').pop().toLowerCase();
        if (ALLOWED_EXTENSIONS.indexOf(ext) === -1) {
            alert('지원하지 않는 파일 형식입니다.\nMP4, AVI, MOV 파일만 업로드할 수 있습니다.');
            return;
        }

        // Validate size
        if (file.size > MAX_SIZE_MB * 1024 * 1024) {
            alert('파일이 너무 큽니다.\n최대 ' + MAX_SIZE_MB + 'MB까지 업로드할 수 있습니다.');
            return;
        }

        selectedFile = file;
        fileName.textContent = file.name;
        fileSize.textContent = formatSize(file.size);
        dropZoneContent.classList.add('hidden');
        fileInfo.classList.remove('hidden');
        uploadBtn.disabled = false;
    }

    function clearFile() {
        selectedFile = null;
        fileInput.value = '';
        dropZoneContent.classList.remove('hidden');
        fileInfo.classList.add('hidden');
        uploadBtn.disabled = true;
    }

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    // -- Upload & Analyze --

    uploadForm.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!selectedFile) return;

        var sourceType = document.getElementById('source-type').value;
        var weapon = document.getElementById('weapon').value;

        uploadBtn.disabled = true;
        progressSection.classList.remove('hidden');

        var formData = new FormData();
        formData.append('file', selectedFile);
        formData.append('source_type', sourceType);
        formData.append('weapon', weapon);

        var xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', function (e) {
            if (e.lengthComputable) {
                var pct = Math.round((e.loaded / e.total) * 100);
                progressBar.style.width = pct + '%';
                progressPct.textContent = pct + '%';
                if (pct > 0) progressBar.classList.add('progress-animated');
            }
        });

        xhr.addEventListener('load', function () {
            progressBar.classList.remove('progress-animated');

            if (xhr.status >= 200 && xhr.status < 300) {
                var resp = JSON.parse(xhr.responseText);

                // Start analysis using video_id (preferred) or video_path
                startAnalysis(resp.video_id, resp.video_path, weapon, sourceType);
            } else {
                alert('업로드 실패: ' + xhr.statusText);
                uploadBtn.disabled = false;
                progressSection.classList.add('hidden');
            }
        });

        xhr.addEventListener('error', function () {
            alert('네트워크 오류가 발생했습니다.');
            uploadBtn.disabled = false;
            progressSection.classList.add('hidden');
        });

        xhr.open('POST', '/api/analytics/upload');
        xhr.send(formData);
    });

    function startAnalysis(videoId, videoPath, weapon, sourceType) {
        progressPct.textContent = '분석 요청 중...';

        fetch('/api/analytics/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_id: videoId,
                video_path: videoPath,
                weapon: weapon,
                source_type: sourceType,
                enable_pose: true,
                enable_action: true,
            }),
        })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
            // Show success message
            uploadForm.classList.add('hidden');
            progressSection.classList.add('hidden');
            uploadSuccess.classList.remove('hidden');

            // Auto-redirect to dashboard after 3 seconds
            setTimeout(function () {
                window.location.href = '/dashboard';
            }, 3000);
        })
        .catch(function (err) {
            alert('분석 시작 실패: ' + err.message);
            uploadBtn.disabled = false;
        });
    }
})();
