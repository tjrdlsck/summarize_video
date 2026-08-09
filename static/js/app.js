const { useState, useRef, useEffect, useMemo } = React;

// --- [Main Application (Refactored UI v2)] --- 
function App() {
    // View Mode: 'dashboard' | 'player' | 'studio'
    const [viewMode, setViewMode] = useState('dashboard');
    // Dashboard Mode: 'analysis' | 'subtitle'
    const [dashboardTab, setDashboardTab] = useState('analysis');

    // Data State
    const [urlInput, setUrlInput] = useState("");
    const [titleInput, setTitleInput] = useState("");
    const [contentType, setContentType] = useState("streaming");
    const [historyList, setHistoryList] = useState([]);
    const [activeTasks, setActiveTasks] = useState([]);
    const [playerData, setPlayerData] = useState(null);
    const [blogData, setBlogData] = useState(null);
    const [uploadStatusText, setUploadStatusText] = useState("");

    // Subtitle Studio State
    const [selectedStudioItem, setSelectedStudioItem] = useState(null);
    const [studioTranscript, setStudioTranscript] = useState(null);
    const [studioSettings, setStudioStudioSettings] = useState({
        maxChars: 20,
        maxLines: 2,
        removePunctuation: true
    });
    const [studioSearch, setStudioSearch] = useState("");
    const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);

    // Folder & Selection State
    const [folders, setFolders] = useState([]);
    const [currentFolder, setCurrentFolder] = useState(null); // null = All videos, 'root' = Uncategorized, or folder ID
    const [selectedCards, setSelectedCards] = useState([]);
    const [dragOverFolder, setDragOverFolder] = useState(null);
    const [lastSelectedIdx, setLastSelectedIdx] = useState(null);
    const [isSelectionMode, setIsSelectionMode] = useState(false);

    // Regenerate Modal State
    const [isRegenerateModalOpen, setIsRegenerateModalOpen] = useState(false);
    const [regenerateTarget, setRegenerateTarget] = useState(null);

    // System Update State
    const [updateAvailable, setUpdateAvailable] = useState(false);
    const [updateInfo, setUpdateInfo] = useState(null);
    const [isUpdating, setIsUpdating] = useState(false);
    const [restartStatus, setRestartStatus] = useState({ pending: false, remaining_seconds: null, reason: null });
    const restartAlertShownRef = useRef(false);
    const notifiedFailedTasksRef = useRef(new Set());

    // Settings & Log Viewer State
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const [isLogViewerOpen, setIsLogViewerOpen] = useState(false);

    // Player UI & Controls State
    const [loading, setLoading] = useState(false);
    const [activeTab, setActiveTab] = useState('chapters'); // 'chapters' | 'shorts' | 'blog' | 'transcript'
    const [expandedChapters, setExpandedChapters] = useState({});
    const [uploadProgress, setUploadProgress] = useState(0);

    // Video Player Extra State
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [playbackRate, setPlaybackRate] = useState(1.0);
    const [volume, setVolume] = useState(1.0);
    const [isMuted, setIsMuted] = useState(false);
    const [isControlsVisible, setIsControlsVisible] = useState(true);
    const controlsTimeoutRef = useRef(null);

    // Inline Title Edit State
    const [isEditingTitle, setIsEditingTitle] = useState(false);
    const [editTitleText, setEditTitleText] = useState("");

    // Shorts Export Modal State
    const [isClipMode, setIsClipMode] = useState(false);
    const [clipTitle, setClipTitle] = useState("");
    const [clipStart, setClipStart] = useState(0);
    const [clipEnd, setClipEnd] = useState(10);
    const [isExporting, setIsExporting] = useState(false);
    const [clipsList, setClipsList] = useState([]);
    const [disabledSkips, setDisabledSkips] = useState({});
    const [activeShortsId, setActiveShortsId] = useState(null);
    const [currentShortsOriginalTime, setCurrentShortsOriginalTime] = useState(0);
    const [currentSubtitle, setCurrentSubtitle] = useState("");
    const [currentShortsSubtitle, setCurrentShortsSubtitle] = useState("");

    // Refs
    const videoRef = useRef(null);
    const itemRefs = useRef({});
    const historyListRef = useRef(historyList);
    const isSelectionModeRef = useRef(isSelectionMode);
    const selectedCardsRef = useRef(selectedCards);

    useEffect(() => { historyListRef.current = historyList; }, [historyList]);
    useEffect(() => { isSelectionModeRef.current = isSelectionMode; }, [isSelectionMode]);
    useEffect(() => { selectedCardsRef.current = selectedCards; }, [selectedCards]);

    // Initial Data Fetching
    useEffect(() => {
        fetchHistory();
        fetchFolders();
        fetchTasks();
        checkSystemUpdate();

        const taskInterval = setInterval(fetchTasks, 3000);
        const updateInterval = setInterval(checkSystemUpdate, 30000);
        const restartInterval = setInterval(checkRestartStatus, 2000);

        return () => {
            clearInterval(taskInterval);
            clearInterval(updateInterval);
            clearInterval(restartInterval);
        };
    }, []);

    useEffect(() => {
        if (playerData && playerData.chapters) {
            const initialStates = {};
            playerData.chapters.forEach((_, index) => {
                initialStates[index] = true;
            });
            setExpandedChapters(initialStates);
        }
    }, [playerData]);

    // --- Helper Functions ---
    const toggleChapter = (index) => {
        setExpandedChapters(prev => ({
            ...prev,
            [index]: !prev[index]
        }));
    };

    const setAllChapters = (isExpanded) => {
        if (!playerData || !playerData.chapters) return;
        const newStates = {};
        playerData.chapters.forEach((_, index) => {
            newStates[index] = isExpanded;
        });
        setExpandedChapters(newStates);
    };

    const seekVideo = (seconds) => {
        if (videoRef.current) {
            videoRef.current.currentTime = seconds;
            videoRef.current.play().catch(() => {});
        }
    };

    window.seekFromTimestamp = (seconds) => {
        seekVideo(seconds);
    };

    const fetchClipsList = async (filename) => {
        try {
            const res = await axios.get(`/api/clips/${filename}?t=${Date.now()}`);
            setClipsList(res.data.clips || []);
        } catch (e) {
            console.error("Failed to fetch clips list", e);
        }
    };

    const handleDeleteClip = async (clipId) => {
        if (!confirm("이 클립을 삭제하시겠습니까? (원본 영상이나 JSON 파일은 유지됩니다)")) return;
        try {
            await axios.delete(`/api/clips/${playerData.video_filename}/${clipId}`);
            setClipsList(prev => prev.filter(c => c.clip_id !== clipId));
        } catch (e) {
            alert("클립 삭제 실패: " + (e.response?.data?.detail || e.message));
        }
    };

    const toggleSkip = (shortsUniqueKey, skipIdx) => {
        const key = `${shortsUniqueKey}_${skipIdx}`;
        setDisabledSkips(prev => ({
            ...prev,
            [key]: !prev[key]
        }));
    };

    const handleDownloadOriginalVideo = () => {
        if (!playerData || !playerData.video_filename) return;
        const videoUrl = `/static/videos/${playerData.video_filename}`;
        const a = document.createElement('a');
        a.href = videoUrl;
        a.download = playerData.video_filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    const handleAutoGenerateShorts = async (e, filename) => {
        e && e.stopPropagation();
        if (!confirm("AI가 비디오를 분석하여 숏츠 하이라이트를 생성하시겠습니까?")) return;
        try {
            await axios.post('/api/shorts/auto-generate', { filename });
            alert("AI 숏츠 생성이 요청되었습니다. 백그라운드 작업 대기열을 확인하세요.");
            fetchTasks();
        } catch (err) {
            alert("숏츠 생성 요청 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const handleExportPremiere = async (e, clipId) => {
        e && e.stopPropagation();
        const clip = playerData.shorts_clips.find(c => c.id === clipId || `${playerData.video_filename}_${c.id}` === clipId);
        if (!clip) return;

        const uniqueKey = `${playerData.video_filename}_${clip.id}`;
        const activeSkips = (clip.skips || []).filter((_, idx) => !disabledSkips[`${uniqueKey}_${idx}`]);

        try {
            const response = await axios.post('/api/export/premiere', {
                video_filename: playerData.video_filename,
                segments: clip.segments,
                skips: activeSkips,
                title: clip.title
            });

            const blob = new Blob([response.data], { type: 'application/xml' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${playerData.video_title || 'shorts'}_${clip.title}.xml`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (err) {
            alert("프리미어 프로 내보내기 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const fetchFolders = async () => {
        try {
            const res = await axios.get(`/api/folders?t=${Date.now()}`);
            setFolders(res.data.folders || []);
        } catch (e) {
            console.error("Failed to fetch folders", e);
        }
    };

    const handleCreateFolder = async () => {
        const name = prompt("새 폴더 이름을 입력하세요:");
        if (!name || !name.trim()) return;
        try {
            await axios.post('/api/folders', { name: name.trim() });
            fetchFolders();
        } catch (e) {
            alert("폴더 생성 실패: " + (e.response?.data?.detail || e.message));
        }
    };

    const handleDeleteFolder = async (folderId, folderName) => {
        if (!confirm(`'${folderName}' 폴더를 삭제하시겠습니까?\n(폴더 안의 비디오는 미분류 항목으로 이동됩니다.)`)) return;
        try {
            await axios.delete(`/api/folders/${folderId}`);
            if (currentFolder === folderId) setCurrentFolder(null);
            fetchFolders();
            fetchHistory();
        } catch (e) {
            alert("폴더 삭제 실패: " + (e.response?.data?.detail || e.message));
        }
    };

    const handleMoveToFolder = async (filenames, folderId) => {
        try {
            for (const filename of filenames) {
                await axios.post('/api/folders/move', { filename, folder_id: folderId });
            }
            setSelectedCards([]);
            fetchHistory();
            fetchFolders();
        } catch (e) {
            alert("폴더 이동 실패: " + (e.response?.data?.detail || e.message));
        }
    };

    const handleRegenerateSubmit = async (data) => {
        if (!regenerateTarget) return;
        try {
            await axios.post('/api/transcribe', {
                filename: regenerateTarget.filename,
                title: regenerateTarget.title,
                content_type: data.contentType,
                run_transcription: data.runTranscription,
                run_summary: data.runSummary,
                run_blog: data.runBlog,
                whisper_lang: data.whisperLang,
                whisper_prompt: data.whisperPrompt,
                whisper_condition: data.whisperCondition,
                whisper_temp: data.whisperTemp,
                whisper_vad: data.whisperVad
            });
            setIsRegenerateModalOpen(false);
            setRegenerateTarget(null);
            fetchTasks();
            alert("재생성 작업이 요청되었습니다.");
        } catch (err) {
            alert("재생성 요청 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const checkRestartStatus = async () => {
        try {
            const res = await axios.get(`/api/system/restart-status?t=${Date.now()}`);
            setRestartStatus(res.data || { pending: false });
            if (res.data && res.data.pending && !restartAlertShownRef.current) {
                restartAlertShownRef.current = true;
                alert(`시스템이 재시작 대기 중입니다 (${res.data.reason}). 남은 시간: ${res.data.remaining_seconds}초`);
            }
        } catch (e) {}
    };

    const checkSystemUpdate = async () => {
        try {
            const res = await axios.get('/api/system/check-update');
            setUpdateAvailable(res.data.update_available);
            setUpdateInfo(res.data);
        } catch (e) {}
    };

    const handleSystemUpdate = async () => {
        if (!confirm("최신 버전으로 업데이트를 진행하시겠습니까?\n업데이트 완료 후 시스템이 자동 재시작됩니다.")) return;
        setIsUpdating(true);
        try {
            await axios.post('/api/system/update');
            alert("업데이트가 성공적으로 시작되었습니다. 시스템이 곧 재부팅됩니다.");
        } catch (err) {
            alert("업데이트 실패: " + (err.response?.data?.detail || err.message));
            setIsUpdating(false);
        }
    };

    const handleRestartNow = async () => {
        if (!confirm("지금 시스템을 재시작하시겠습니까?")) return;
        try {
            await axios.post('/api/system/restart-now');
            alert("시스템 재시작이 요청되었습니다. 5초 후 페이지를 새로고침합니다.");
            setTimeout(() => window.location.reload(), 5000);
        } catch (err) {
            alert("재시작 요청 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const fetchHistory = async () => {
        try {
            const res = await axios.get(`/api/history?t=${Date.now()}`);
            const list = Array.isArray(res.data) ? res.data : (res.data.history || []);
            setHistoryList(list);
        } catch (e) {
            console.error("Failed to fetch history", e);
        }
    };

    const fetchTasks = async () => {
        try {
            const res = await axios.get(`/api/tasks?t=${Date.now()}`);
            const tasks = res.data.tasks || [];
            setActiveTasks(tasks);

            tasks.forEach(t => {
                if (t.status === 'failed' && !notifiedFailedTasksRef.current.has(t.task_id)) {
                    notifiedFailedTasksRef.current.add(t.task_id);
                }
            });
        } catch (e) {}
    };

    const handleModalSubmit = async (data) => {
        setIsUploadModalOpen(false);
        if (data.mode === 'url') {
            try {
                await axios.post('/api/transcribe', {
                    url: data.url,
                    title: data.title,
                    content_type: data.contentType,
                    run_transcription: true,
                    run_summary: data.runSummary,
                    run_blog: data.runBlog,
                    whisper_lang: data.whisperLang,
                    whisper_prompt: data.whisperPrompt,
                    whisper_condition: data.whisperCondition,
                    whisper_temp: data.whisperTemp,
                    whisper_vad: data.whisperVad
                });
                alert("URL 분석이 성공적으로 요청되었습니다.");
                fetchTasks();
            } catch (err) {
                alert("URL 분석 요청 실패: " + (err.response?.data?.detail || err.message));
            }
        } else if (data.mode === 'file' && data.file) {
            await handleFileUpload(
                data.file, data.title, data.contentType, data.runSummary, data.runBlog,
                data.whisperLang, data.whisperPrompt, data.whisperCondition, data.whisperTemp, data.whisperVad
            );
        }
    };

    const handleStartAnalysis = async (e, filename, title, requestContentType = contentType) => {
        e && e.stopPropagation();
        try {
            await axios.post('/api/analyze', {
                filename,
                title,
                content_type: requestContentType
            });
            alert("AI 분석이 요청되었습니다.");
            fetchTasks();
        } catch (err) {
            alert("분석 요청 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const handleGenerateBlog = async (e, filename) => {
        e && e.stopPropagation();
        try {
            await axios.post('/api/blog/generate', { filename });
            alert("블로그 포스트 완성이 요청되었습니다.");
            fetchTasks();
        } catch (err) {
            alert("블로그 생성 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const handleFileUpload = async (file, customTitle, ctType, runSummary, runBlog, wLang, wPrompt, wCond, wTemp, wVad) => {
        const chunkSize = 5 * 1024 * 1024; // 5MB
        const totalChunks = Math.ceil(file.size / chunkSize);
        const safeIdentifier = `${file.name}_${file.size}_${file.lastModified}`;

        setUploadProgress(0);
        setUploadStatusText("업로드 준비 중...");

        try {
            let startChunkIndex = 0;
            try {
                const statusRes = await axios.get(`/api/upload/status/${safeIdentifier}`);
                startChunkIndex = statusRes.data.uploaded_chunks || 0;
            } catch (e) {}

            for (let i = startChunkIndex; i < totalChunks; i++) {
                const start = i * chunkSize;
                const end = Math.min(file.size, start + chunkSize);
                const chunk = file.slice(start, end);

                const formData = new FormData();
                formData.append('file', chunk);
                formData.append('identifier', safeIdentifier);
                formData.append('chunk_number', i);
                formData.append('total_chunks', totalChunks);
                formData.append('filename', file.name);

                await axios.post('/api/upload/chunk', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });

                const pct = Math.round(((i + 1) / totalChunks) * 100);
                setUploadProgress(pct);
                setUploadStatusText(`업로드 진행 중 (${pct}%) - ${i + 1}/${totalChunks} 청크`);
            }

            setUploadStatusText("업로드 완료! 서버 병합 처리 중...");

            const completeRes = await axios.post('/api/upload/complete', {
                identifier: safeIdentifier,
                filename: file.name,
                total_chunks: totalChunks
            });

            const savedFilename = completeRes.data.filename;

            await axios.post('/api/transcribe', {
                filename: savedFilename,
                title: customTitle || file.name,
                content_type: ctType || contentType,
                run_transcription: true,
                run_summary: runSummary,
                run_blog: runBlog,
                whisper_lang: wLang,
                whisper_prompt: wPrompt,
                whisper_condition: wCond,
                whisper_temp: wTemp,
                whisper_vad: wVad
            });

            alert("파일 업로드 및 작업 요청이 완료되었습니다.");
            fetchHistory();
            fetchTasks();
        } catch (err) {
            alert("업로드 실패: " + (err.response?.data?.detail || err.message));
        } finally {
            setUploadProgress(0);
            setUploadStatusText("");
        }
    };

    const handleDelete = async (e, filename) => {
        e && e.stopPropagation();
        if (!confirm(`'${filename}' 항목을 정말 삭제하시겠습니까?`)) return;
        try {
            await axios.delete(`/api/history/${filename}`);
            if (playerData && playerData.video_filename === filename) {
                setViewMode('dashboard');
                setPlayerData(null);
            }
            fetchHistory();
        } catch (err) {
            alert("삭제 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const handleCancelTask = async (taskId, skipConfirm = false) => {
        if (!skipConfirm && !confirm("이 작업을 중단/취소하시겠습니까?")) return;
        try {
            await axios.delete(`/api/tasks/${taskId}`);
            fetchTasks();
        } catch (err) {
            alert("작업 취소 실패: " + (err.response?.data?.detail || err.message));
        }
    };

    const handleSelectHistoryItem = async (item) => {
        const fn = item.filename || item.video_filename || item.result_data?.video_filename;
        setLoading(true);
        setViewMode('player');
        setActiveTab('chapters');
        setIsClipMode(false);
        setEditTitleText(item.title || fn);
        setIsEditingTitle(false);

        let transcriptData = null;
        if (item.result_data && item.result_data.transcript_json_filename) {
            try {
                const tRes = await axios.get(`/static/results/${item.result_data.transcript_json_filename}?t=${Date.now()}`);
                transcriptData = tRes.data;
            } catch (e) {}
        }

        let blogResData = null;
        const baseName = fn ? (fn.substring(0, fn.lastIndexOf('.')) || fn) : '';
        try {
            const bRes = await axios.get(`/static/results/${baseName}_blog_view.json?t=${Date.now()}`).catch(() => null);
            if (bRes) blogResData = bRes.data;
        } catch (e) {}

        const mergedData = {
            ...item,
            video_filename: fn,
            video_title: item.title || item.video_title || fn,
            chapters: item.result_data?.chapters || [],
            total_chapters: item.result_data?.total_chapters || 0,
            summary_title: item.result_data?.summary_title || item.title,
            overall_summary: item.result_data?.overall_summary || "",
            shorts_clips: item.result_data?.shorts_clips || [],
            transcripts: transcriptData
        };

        setPlayerData(mergedData);
        setBlogData(blogResData);
        setLoading(false);
        if (fn) fetchClipsList(fn);
    };

    const handleTimeUpdate = () => {
        if (!videoRef.current) return;
        const cur = videoRef.current.currentTime;
        setCurrentTime(cur);

        if (playerData && playerData.transcripts) {
            const idx = playerData.transcripts.findIndex(t => cur >= t.start && cur <= t.end);
            if (idx !== -1) {
                if (itemRefs.current[idx]) {
                    itemRefs.current[idx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
                setCurrentSubtitle(playerData.transcripts[idx].text);
            }
        }
    };

    const handleVideoMouseMove = () => {
        setIsControlsVisible(true);
        if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current);
        controlsTimeoutRef.current = setTimeout(() => setIsControlsVisible(false), 3000);
    };

    const handleVideoMouseLeave = () => {
        setIsControlsVisible(false);
    };

    const handleUpdateTitle = async () => {
        if (!playerData || !editTitleText.trim()) return;
        try {
            await axios.post('/api/history/update-title', {
                filename: playerData.video_filename,
                title: editTitleText.trim()
            });
            setPlayerData(prev => ({ ...prev, video_title: editTitleText.trim(), title: editTitleText.trim() }));
            setIsEditingTitle(false);
            fetchHistory();
        } catch (e) {
            alert("제목 수정 실패: " + (e.response?.data?.detail || e.message));
        }
    };

    const handleExportClip = async () => {
        if (!playerData || clipEnd <= clipStart) {
            alert("올바른 클립 시간 범위를 지정하세요.");
            return;
        }
        setIsExporting(true);
        try {
            await axios.post('/api/export/clip', {
                video_filename: playerData.video_filename,
                start_time: clipStart,
                end_time: clipEnd,
                title: clipTitle || "custom_clip"
            });
            alert("클립 내보내기 작업이 백그라운드 대기열에 등록되었습니다.");
            setIsClipMode(false);
            fetchTasks();
        } catch (err) {
            alert("클립 내보내기 실패: " + (err.response?.data?.detail || err.message));
        } finally {
            setIsExporting(false);
        }
    };

    const handleJumpToShortsScript = (e, videoElementId, startSec, clipSegments) => {
        e && e.stopPropagation();
        seekVideo(startSec);
    };

    const handleShortsTimeUpdate = (videoEl, shortsUniqueKey, skips) => {
        if (!videoEl) return;
        const cur = videoEl.currentTime;
        setCurrentShortsOriginalTime(cur);

        const activeSkips = (skips || []).filter((_, idx) => !disabledSkips[`${shortsUniqueKey}_${idx}`]);
        for (const skip of activeSkips) {
            if (cur >= skip.start && cur < skip.end) {
                videoEl.currentTime = skip.end;
                break;
            }
        }

        if (playerData && playerData.transcripts) {
            const currentSub = playerData.transcripts.find(t => cur >= t.start && cur <= t.end);
            if (currentSub) {
                setCurrentShortsSubtitle(currentSub.text);
            }
        }
    };

    const handleDownloadSubtitle = (filename, format = 'srt') => {
        window.open(`/api/download/subtitle/${filename}?format=${format}`, '_blank');
    };

    const handleStudioDownload = (format) => {
        if (!selectedStudioItem) return;
        window.open(`/api/download/subtitle/${selectedStudioItem.filename}?format=${format}&max_chars=${studioSettings.maxChars}&max_lines=${studioSettings.maxLines}&remove_punct=${studioSettings.removePunctuation}`, '_blank');
    };

    // Filtered Video List by Folder & Search
    const filteredHistoryList = useMemo(() => {
        return historyList.filter(item => {
            if (currentFolder === 'root') {
                return !item.folder_id;
            } else if (currentFolder) {
                return item.folder_id === currentFolder;
            }
            return true;
        });
    }, [historyList, currentFolder]);

    // Active Chapters for Timeline Marker calculation
    const chapterMarkers = useMemo(() => {
        if (!playerData || !playerData.chapters || !duration) return [];
        return playerData.chapters.map(c => ({
            pct: (c.time.start / duration) * 100,
            title: c.title
        }));
    }, [playerData, duration]);

    return (
        <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden select-none">
            {/* --- 1. Left Global Navigation Sidebar --- */}
            <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0 z-30">
                {/* Brand Logo Header */}
                <div className="p-5 border-b border-slate-800 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-400 flex items-center justify-center font-black text-white shadow-lg text-lg">
                        V
                    </div>
                    <div>
                        <h1 className="font-outfit font-extrabold text-base tracking-tight text-white leading-none">
                            Insight<span className="text-brand-500">Player</span>
                        </h1>
                        <p className="text-[10px] text-slate-400 font-medium tracking-wider mt-1">AI VIDEO ANALYST v2.0</p>
                    </div>
                </div>

                {/* Primary Nav Menu */}
                <nav className="p-3 space-y-1 flex-1">
                    <button 
                        onClick={() => setViewMode('dashboard')}
                        className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition ${viewMode === 'dashboard' ? 'bg-brand-600 text-white shadow-md shadow-brand-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`}
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                        <span>비디오 대시보드</span>
                    </button>

                    <button 
                        onClick={() => setViewMode('studio')}
                        className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition ${viewMode === 'studio' ? 'bg-brand-600 text-white shadow-md shadow-brand-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}`}
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"></path></svg>
                        <span>자막 스튜디오</span>
                    </button>
                </nav>

                {/* System Settings & Status Footer */}
                <div className="p-3 border-t border-slate-800 space-y-1">
                    <button 
                        onClick={() => setIsSettingsOpen(true)}
                        className="w-full flex items-center justify-between px-4 py-2.5 rounded-xl text-xs font-semibold text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition"
                    >
                        <span className="flex items-center gap-2">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                            시스템 설정
                        </span>
                    </button>

                    <button 
                        onClick={() => setIsLogViewerOpen(true)}
                        className="w-full flex items-center justify-between px-4 py-2.5 rounded-xl text-xs font-semibold text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition"
                    >
                        <span className="flex items-center gap-2">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                            오류 로그 뷰어
                        </span>
                    </button>
                </div>
            </aside>

            {/* --- 2. Main Content Area --- */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-slate-950">
                {/* Global Top Header Bar */}
                <header className="h-16 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-6 flex items-center justify-between shrink-0 z-20">
                    <div className="flex items-center gap-4">
                        {viewMode === 'player' && (
                            <button 
                                onClick={() => setViewMode('dashboard')}
                                className="flex items-center gap-2 text-xs font-bold text-slate-400 hover:text-white bg-slate-800 px-3 py-1.5 rounded-lg transition"
                            >
                                <span>←</span> 대시보드로 돌아가기
                            </button>
                        )}
                        <h2 className="text-sm font-bold text-slate-200 tracking-tight">
                            {viewMode === 'dashboard' ? '비디오 통합 관리 대시보드' :
                             viewMode === 'player' ? (playerData?.video_title || 'Insight Player') : '자막 가공 스튜디오'}
                        </h2>
                    </div>

                    <div className="flex items-center gap-3">
                        {updateAvailable && (
                            <button 
                                onClick={handleSystemUpdate}
                                className="px-3 py-1.5 bg-gradient-to-r from-amber-500 to-orange-500 text-white rounded-lg text-xs font-bold shadow-sm hover:brightness-110 transition animate-pulse flex items-center gap-1.5"
                            >
                                <span>🚀</span> 최신 업데이트 가능
                            </button>
                        )}

                        <button 
                            onClick={() => setIsUploadModalOpen(true)}
                            className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-brand-600/30 transition flex items-center gap-2"
                        >
                            <span className="text-sm font-bold">+</span> 새 비디오 분석
                        </button>
                    </div>
                </header>

                {/* Body View Content Router */}
                <main className="flex-1 overflow-hidden relative">
                    {/* VIEW 1: DASHBOARD */}
                    {viewMode === 'dashboard' && (
                        <div className="h-full flex overflow-hidden">
                            {/* Left Sub Panel: Folders */}
                            <aside className="w-56 border-r border-slate-800/80 p-4 space-y-4 overflow-y-auto custom-scrollbar shrink-0 bg-slate-900/30">
                                <div className="flex justify-between items-center px-1">
                                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">비디오 폴더</span>
                                    <button onClick={handleCreateFolder} className="text-xs text-brand-400 font-bold hover:underline">+ 추가</button>
                                </div>
                                <div className="space-y-1">
                                    <button 
                                        onClick={() => setCurrentFolder(null)}
                                        className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold transition ${currentFolder === null ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-850 hover:text-slate-200'}`}
                                    >
                                        <span className="flex items-center gap-2">📂 전체 동영상</span>
                                        <span className="text-[10px] font-mono opacity-60">{historyList.length}</span>
                                    </button>
                                    <button 
                                        onClick={() => setCurrentFolder('root')}
                                        className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold transition ${currentFolder === 'root' ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-850 hover:text-slate-200'}`}
                                    >
                                        <span className="flex items-center gap-2">📁 미분류</span>
                                        <span className="text-[10px] font-mono opacity-60">{historyList.filter(h => !h.folder_id).length}</span>
                                    </button>
                                    {folders.map(folder => (
                                        <div key={folder.id} className="group relative flex items-center">
                                            <button 
                                                onClick={() => setCurrentFolder(folder.id)}
                                                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-semibold transition ${currentFolder === folder.id ? 'bg-slate-800 text-brand-400' : 'text-slate-400 hover:bg-slate-850 hover:text-slate-200'}`}
                                            >
                                                <span className="flex items-center gap-2 truncate pr-4">📂 {folder.name}</span>
                                            </button>
                                            <button onClick={() => handleDeleteFolder(folder.id, folder.name)} className="absolute right-2 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400 text-xs p-1">✕</button>
                                        </div>
                                    ))}
                                </div>
                            </aside>

                            {/* Main Video Cards Grid */}
                            <section className="flex-1 p-6 overflow-y-auto custom-scrollbar">
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
                                                    <button onClick={(e) => { e.stopPropagation(); setRegenerateTarget(item); setIsRegenerateModalOpen(true); }} className="text-[11px] text-slate-400 hover:text-white font-bold transition">🔄 재생성</button>
                                                    <button onClick={(e) => handleDelete(e, item.video_filename)} className="text-[11px] text-slate-500 hover:text-rose-400 font-bold transition">삭제</button>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </section>
                        </div>
                    )}

                    {/* VIEW 2: INSIGHT PLAYER (Split View 2-Column) */}
                    {viewMode === 'player' && playerData && (
                        <div className="h-full flex overflow-hidden">
                            {/* Left Column (45% Width) - Sticky Video Player & Heatmap */}
                            <div className="w-[45%] border-r border-slate-800 bg-slate-950 flex flex-col shrink-0 p-5 overflow-y-auto custom-scrollbar space-y-4">
                                {/* Title Bar */}
                                <div className="flex justify-between items-center">
                                    {isEditingTitle ? (
                                        <div className="flex gap-2 w-full">
                                            <input type="text" value={editTitleText} onChange={(e) => setEditTitleText(e.target.value)} className="flex-1 bg-slate-900 border border-brand-500 text-xs text-white p-2 rounded-lg outline-none" />
                                            <button onClick={handleUpdateTitle} className="px-3 py-1 bg-brand-600 text-white rounded-lg text-xs font-bold">저장</button>
                                        </div>
                                    ) : (
                                        <h3 onClick={() => setIsEditingTitle(true)} className="font-bold text-base text-slate-100 hover:text-brand-400 transition cursor-pointer truncate" title="클릭하여 제목 수정">
                                            {playerData.video_title || playerData.video_filename} ✏️
                                        </h3>
                                    )}
                                </div>

                                {/* Video Player Card */}
                                <div className="rounded-2xl overflow-hidden bg-black border border-slate-800 shadow-2xl relative">
                                    <video 
                                        ref={videoRef}
                                        src={`/static/videos/${playerData.video_filename}`}
                                        className="w-full aspect-video"
                                        controls
                                        onTimeUpdate={handleTimeUpdate}
                                        onLoadedMetadata={() => setDuration(videoRef.current ? videoRef.current.duration : 0)}
                                    />
                                </div>

                                {/* AI Visual Timeline & Heatmap Chips */}
                                <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 space-y-2">
                                    <div className="flex justify-between items-center text-xs text-slate-400 font-bold">
                                        <span>📍 타임라인 비주얼 마커</span>
                                        <span className="font-mono text-brand-400">{formatTime(currentTime)} / {formatTime(duration)}</span>
                                    </div>
                                    <div className="w-full bg-slate-950 h-3 rounded-full relative overflow-hidden border border-slate-800">
                                        {chapterMarkers.map((m, idx) => (
                                            <div 
                                                key={idx} 
                                                className="timeline-marker timeline-marker-chapter" 
                                                style={{ left: `${m.pct}%` }}
                                                title={m.title}
                                            />
                                        ))}
                                    </div>
                                </div>

                                {/* Quick Tools Toolbar */}
                                <div className="flex justify-between items-center pt-2">
                                    <button onClick={handleDownloadOriginalVideo} className="px-3 py-2 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded-xl text-xs font-semibold border border-slate-800 transition flex items-center gap-1.5">
                                        <span>⬇</span> 원본 영상 다운로드
                                    </button>
                                    <div className="flex gap-2">
                                        <button onClick={() => handleDownloadSubtitle(playerData.video_filename, 'srt')} className="px-3 py-2 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded-xl text-xs font-semibold border border-slate-800 transition">.SRT 자막</button>
                                        <button onClick={() => handleDownloadSubtitle(playerData.video_filename, 'vtt')} className="px-3 py-2 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded-xl text-xs font-semibold border border-slate-800 transition">.VTT 자막</button>
                                    </div>
                                </div>
                            </div>

                            {/* Right Column (55% Width) - Inspector Panel & 4 Tabs */}
                            <div className="flex-1 flex flex-col min-w-0 bg-slate-900/40">
                                {/* Tab Navigation Header */}
                                <div className="flex border-b border-slate-800 px-6 bg-slate-900/80 shrink-0">
                                    {[
                                        { id: 'chapters', label: '📌 AI 챕터 요약' },
                                        { id: 'shorts', label: '✂️ 쇼츠 & 하이라이트' },
                                        { id: 'blog', label: '📝 블로그 뷰' },
                                        { id: 'transcript', label: '💬 자막 대본' }
                                    ].map(tab => (
                                        <button 
                                            key={tab.id}
                                            onClick={() => setActiveTab(tab.id)}
                                            className={`px-5 py-4 text-xs font-bold border-b-2 transition ${activeTab === tab.id ? 'border-brand-500 text-brand-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                                        >
                                            {tab.label}
                                        </button>
                                    ))}
                                </div>

                                {/* Inspector Content Body */}
                                <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                                    {/* TAB 1: CHAPTERS */}
                                    {activeTab === 'chapters' && (
                                        <div className="space-y-4">
                                            {playerData.chapters && playerData.chapters.length > 0 ? (
                                                playerData.chapters.map((chap, idx) => (
                                                    <div key={idx} className="bg-slate-900 rounded-xl border border-slate-800 p-4 space-y-2 hover:border-slate-700 transition">
                                                        <div className="flex justify-between items-center">
                                                            <button onClick={() => seekVideo(chap.time.start)} className="text-xs font-mono font-bold text-brand-400 hover:underline">
                                                                ▶ {formatTime(chap.time.start)}
                                                            </button>
                                                            <h4 className="font-bold text-sm text-slate-100 flex-1 ml-3">{chap.title}</h4>
                                                        </div>
                                                        <p className="text-xs text-slate-400 leading-relaxed pl-7">{chap.summary}</p>
                                                    </div>
                                                ))
                                            ) : (
                                                <div className="text-center py-20 text-slate-500 text-xs">AI 챕터 분석 결과가 없습니다.</div>
                                            )}
                                        </div>
                                    )}

                                    {/* TAB 2: SHORTS */}
                                    {activeTab === 'shorts' && (
                                        <div className="space-y-4">
                                            {playerData.shorts_clips && playerData.shorts_clips.length > 0 ? (
                                                playerData.shorts_clips.map((clip, idx) => (
                                                    <div key={idx} className="bg-slate-900 rounded-xl border border-slate-800 p-4 space-y-3">
                                                        <div className="flex justify-between items-center">
                                                            <h4 className="font-bold text-sm text-slate-100">{clip.title}</h4>
                                                            <button onClick={(e) => handleExportPremiere(e, clip.id)} className="text-xs font-bold text-emerald-400 hover:underline">XML 내보내기</button>
                                                        </div>
                                                        <p className="text-xs text-slate-400">{clip.reason}</p>
                                                    </div>
                                                ))
                                            ) : (
                                                <div className="text-center py-20 text-slate-500 text-xs">추천된 쇼츠 구간이 없습니다.</div>
                                            )}
                                        </div>
                                    )}

                                    {/* TAB 3: BLOG */}
                                    {activeTab === 'blog' && (
                                        <div className="space-y-4">
                                            {blogData ? (
                                                <div className="bg-slate-900 p-6 rounded-xl border border-slate-800 text-xs text-slate-300 leading-relaxed">
                                                    <h2 className="text-lg font-bold text-white mb-4">{blogData.blog_title}</h2>
                                                    <div dangerouslySetInnerHTML={{ __html: marked.parse(blogData.chapters.map(c => `### ${c.title}\n\n${c.content}`).join("\n\n")) }} />
                                                </div>
                                            ) : (
                                                <div className="text-center py-20 text-slate-500 text-xs">생성된 블로그 데이터가 없습니다.</div>
                                            )}
                                        </div>
                                    )}

                                    {/* TAB 4: TRANSCRIPT */}
                                    {activeTab === 'transcript' && (
                                        <div className="space-y-2">
                                            {playerData.transcripts ? (
                                                playerData.transcripts.map((t, idx) => (
                                                    <div 
                                                        key={idx} 
                                                        ref={el => itemRefs.current[idx] = el}
                                                        onClick={() => seekVideo(t.start)}
                                                        className="p-3 rounded-lg hover:bg-slate-850 cursor-pointer flex gap-3 text-xs transition"
                                                    >
                                                        <span className="font-mono text-brand-400 shrink-0">{formatTime(t.start)}</span>
                                                        <p className="text-slate-300">{t.text}</p>
                                                    </div>
                                                ))
                                            ) : (
                                                <div className="text-center py-20 text-slate-500 text-xs">자막 데이터가 없습니다.</div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* VIEW 3: SUBTITLE STUDIO */}
                    {viewMode === 'studio' && (
                        <div className="h-full p-6 overflow-y-auto custom-scrollbar space-y-6">
                            <div className="bg-slate-900 p-6 rounded-2xl border border-slate-800 flex justify-between items-center">
                                <div>
                                    <h3 className="font-bold text-lg text-white">자막 가공 스튜디오</h3>
                                    <p className="text-xs text-slate-400 mt-1">자막의 줄당 글자 수 및 구두점 규칙을 커스텀 가공하여 파일로 다운로드합니다.</p>
                                </div>
                                <div className="flex gap-3">
                                    <button onClick={() => handleStudioDownload('srt')} className="px-4 py-2 bg-brand-600 text-white text-xs font-bold rounded-xl shadow-md">.SRT 다운로드</button>
                                    <button onClick={() => handleStudioDownload('vtt')} className="px-4 py-2 bg-slate-800 text-white text-xs font-bold rounded-xl">.VTT 다운로드</button>
                                </div>
                            </div>
                        </div>
                    )}
                </main>
            </div>

            {/* --- Global Modals & Widgets --- */}
            {window.TaskMonitor && <window.TaskMonitor tasks={activeTasks} onCancel={handleCancelTask} />}
            {window.SettingsModal && <window.SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />}
            {window.LogViewerModal && <window.LogViewerModal isOpen={isLogViewerOpen} onClose={() => setIsLogViewerOpen(false)} />}
            {window.VideoUploadModal && (
                <window.VideoUploadModal 
                    isOpen={isUploadModalOpen} 
                    onClose={() => setIsUploadModalOpen(false)} 
                    onSubmit={handleModalSubmit}
                    uploadProgress={uploadProgress}
                    uploadStatusText={uploadStatusText}
                    isUploading={uploadProgress > 0}
                />
            )}
            {window.RegenerateModal && (
                <window.RegenerateModal 
                    isOpen={isRegenerateModalOpen}
                    onClose={() => setIsRegenerateModalOpen(false)}
                    onSubmit={handleRegenerateSubmit}
                    initialContentType={regenerateTarget?.content_type}
                    hasChapters={!!regenerateTarget?.result_data?.chapters}
                />
            )}
        </div>
    );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
