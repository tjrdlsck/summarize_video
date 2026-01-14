const { useState, useRef, useEffect, useMemo } = React;

// --- [Main Application] --- 
function App() {
    // View Mode: 'dashboard' | 'player' 
    const [viewMode, setViewMode] = useState('dashboard');
    // Dashboard Mode: 'analysis' | 'subtitle'
    const [dashboardTab, setDashboardTab] = useState('analysis');

    // Data State
    const [urlInput, setUrlInput] = useState("");
    const [titleInput, setTitleInput] = useState("");
    const [historyList, setHistoryList] = useState([]);
    const [activeTasks, setActiveTasks] = useState([]);
    const [playerData, setPlayerData] = useState(null);
    const [blogData, setBlogData] = useState(null);

    // Subtitle Studio State
    const [selectedStudioItem, setSelectedStudioItem] = useState(null);
    const [studioTranscript, setStudioTranscript] = useState(null);
    const [studioSettings, setStudioStudioSettings] = useState({
        maxChars: 20,
        maxLines: 2,
        removePunctuation: true
    });
    const [studioSearch, setStudioSearch] = useState("");
    const [isUploadPanelOpen, setIsUploadPanelOpen] = useState(false);

    // [New] System Update State
    const [updateAvailable, setUpdateAvailable] = useState(false);
    const [updateInfo, setUpdateInfo] = useState(null);
    const [isUpdating, setIsUpdating] = useState(false);

    // [New] Settings State
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);

    // Player UI State
    const [loading, setLoading] = useState(false);
    const [activeTab, setActiveTab] = useState('chapters');
    const [expandedChapters, setExpandedChapters] = useState({});

    useEffect(() => {
        if (playerData && playerData.chapters) {
            const initialStates = {};
            playerData.chapters.forEach((_, index) => {
                initialStates[index] = true;
            });
            setExpandedChapters(initialStates);
        }
    }, [playerData]);

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

    const [isEditingTitle, setIsEditingTitle] = useState(false);
    const [editTitleText, setEditTitleText] = useState("");
    const [showSubtitle, setShowSubtitle] = useState(true);
    const [currentSubtitle, setCurrentSubtitle] = useState("");
    const [isControlsVisible, setIsControlsVisible] = useState(false);
    const controlsTimeoutRef = useRef(null);
    const [isClipMode, setIsClipMode] = useState(false);
    const [clipStart, setClipStart] = useState(0);
    const [clipEnd, setClipEnd] = useState(0);
    const [isExporting, setIsExporting] = useState(false);
    const [clipsList, setClipsList] = useState([]);
    const [clipTitle, setClipTitle] = useState("");
    const [totalDuration, setTotalDuration] = useState(0);
    const [activeIndex, setActiveIndex] = useState(-1);
    const itemRefs = useRef([]);

    const blogContent = useMemo(() => {
        if (!playerData || !playerData.chapters || !playerData.transcripts) return [];
        return playerData.chapters.map((chapter, idx) => {
            const nextChapterStart = playerData.chapters[idx + 1]?.time.start || Infinity;
            const endTime = Math.min(chapter.time.end, nextChapterStart);
            const scripts = playerData.transcripts.filter(t =>
                t.start >= chapter.time.start && t.start < endTime
            );
            const fullText = scripts.map(s => s.text).join(" ");
            return {
                ...chapter,
                fullText: fullText || "(대사 없음. 음악이나 무음 구간일 수 있습니다.)"
            };
        });
    }, [playerData]);

    const fetchClips = async (filename) => {
        try {
            const res = await axios.get(`/api/clips/${filename}?t=${Date.now()}`);
            setClipsList(res.data);
        } catch (err) {
            console.error("Failed to fetch clips:", err);
        }
    };

    const handleDeleteClip = async (clipId) => {
        if (!confirm(`정말로 이 클립을 삭제하시겠습니까?`)) return;
        try {
            await axios.delete(`/api/clips/${playerData.video_filename}/${clipId}`);
            fetchClips(playerData.video_filename);
        } catch (err) {
            alert("삭제 실패: " + err.message);
        }
    };

    const handleDownloadOriginalVideo = () => {
        const isYoutubeSource = !/^[0-9a-fA-F]{8}_/.test(playerData.video_filename);
        let downloadName = playerData.video_filename;
        
        if (isYoutubeSource) {
            downloadName = (playerData.video_title || "original_video").replace(/\s+/g, '_') + ".mp4";
        } else {
            // 로컬 업로드인 경우 UUID_ 제거 시도
            downloadName = playerData.video_filename.replace(/^[0-9a-fA-F]{8}_/, '');
        }

        // [개선] 크롬 호환성을 위해 ?download=true 파라미터 추가
        const link = document.createElement('a');
        link.href = `/api/stream/video/${playerData.video_filename}?download=true`;
        link.setAttribute('download', downloadName);
        document.body.appendChild(link);
        link.click();
        link.remove();
    };
    
    const handleExportPremiere = async (e, clipId) => {
        e.preventDefault();
        e.stopPropagation();

        // [New Logic] 영상 출처에 따른 기본 파일명 제안
        const isYoutubeSource = !/^[0-9a-fA-F]{8}_/.test(playerData.video_filename);
        let defaultFileName = playerData.video_filename;
        if (isYoutubeSource) {
            defaultFileName = (playerData.video_title || "video").trim() + ".mp4";
        } else {
            defaultFileName = playerData.video_filename.replace(/^[0-9a-fA-F]{8}_/, '');
        }

        const customFilename = prompt(`프리미어 프로에서 연결할 실제 영상 파일의 이름을 확인해주세요.
(정확히 일치해야 자동으로 연결됩니다)`, defaultFileName);

        if (customFilename === null) return; // 취소 시 중단

        // [Add] 자막 규격 입력 (쇼츠 최적화 기본값 10자, 2줄)
        const maxCharsStr = prompt("자막 한 줄당 최대 글자 수를 입력하세요 (쇼츠 권장: 10~15):", "10");
        if (maxCharsStr === null) return;
        const maxChars = parseInt(maxCharsStr) || 10;

        const maxLinesStr = prompt("자막 최대 표시 줄 수를 입력하세요 (기본값: 2):", "2");
        if (maxLinesStr === null) return;
        const maxLines = parseInt(maxLinesStr) || 2;

        try {
            const response = await axios.post('/api/export/premiere', {
                video_filename: playerData.video_filename,
                clip_id: clipId,
                custom_video_filename: customFilename.trim(),
                max_chars: maxChars,
                max_lines: maxLines
            }, {
                responseType: 'blob' 
            });
            
            // [Fix] 서버 응답 타입에 따라 기본 확장자 결정
            const isZip = response.data.type === 'application/zip';
            const defaultExt = isZip ? '.zip' : '.xml';
            let fileName = `Premiere_Seq_${clipId.substring(0,8)}${defaultExt}`;

            // [Fix] 서버가 보낸 파일명이 있으면 최우선 사용 (CORS expose_headers 설정 필요)
            const contentDisposition = response.headers['content-disposition'];
            if (contentDisposition) {
                const fileNameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
                if (fileNameMatch && fileNameMatch.length === 2) {
                    fileName = fileNameMatch[1];
                }
            }

            const url = window.URL.createObjectURL(new Blob([response.data], { type: response.data.type }));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', fileName);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            console.error(err);
            alert("XML 내보내기 실패: 서버 오류가 발생했습니다.");
        }
    };

    const videoRef = useRef(null);

    // --- [Lifecycle & Polling] ---
    useEffect(() => {
        fetchHistory();
        checkUpdate(); // [New] 앱 로드 시 업데이트 확인
        const interval = setInterval(fetchActiveTasks, 2000);
        return () => clearInterval(interval);
    }, []);

    // [New] 업데이트 확인 핸들러
    const checkUpdate = async () => {
        try {
            const res = await axios.get('/api/system/check-update');
            if (res.data.update_available) {
                setUpdateAvailable(true);
                setUpdateInfo(res.data);
            }
        } catch (err) { console.error("Update check failed", err); }
    };

    // [New] 시스템 업데이트 실행 핸들러
    const handleSystemUpdate = async () => {
        if (!confirm(`시스템 업데이트를 진행하시겠습니까?

- 최신 코드를 다운로드하고 의존성을 재설치합니다.
- 로컬에서 수정된 코드가 있다면 원본으로 초기화될 수 있습니다.
- 완료 후 서버가 자동으로 재시작됩니다.`)) return;

        setIsUpdating(true);
        try {
            await axios.post('/api/system/update');
            
            // [New Strategy] Smart Polling Restart
            // 서버가 꺼지고 다시 켜질 때까지 기다린 후 새로고침합니다.
            alert("업데이트가 시작되었습니다. 서버 재시작 완료 시 자동으로 페이지를 불러옵니다.");
            
            const pollServer = async () => {
                try {
                    // 서버의 루트(/) 경로에 2초마다 핑을 보냅니다.
                    await axios.get('/?t=' + Date.now(), { timeout: 1500 });
                    // 성공하면(서버가 다시 뜸) 새로고침
                    window.location.reload();
                } catch (e) {
                    // 에러가 나면(서버가 아직 죽어있음) 계속 시도
                    setTimeout(pollServer, 2000);
                }
            };

            // 5초 뒤부터 서버 체크 시작 (업데이트 작업 시간을 고려)
            setTimeout(pollServer, 5000);

        } catch (err) {
            if (err.code === 'ECONNABORTED' || !err.response) {
                // 이미 서버가 종료되어 연결이 끊긴 경우도 성공으로 간주하고 폴링 시작
                alert("서버 재시작 대기 중... 자동으로 페이지를 불러옵니다.");
                window.location.reload(); // 폴링 로직이 alert 후 바로 탈 수도 있으므로 안전하게 처리
            } else {
                alert("업데이트 실패: " + err.message);
                setIsUpdating(false);
            }
        }
    };

    // 작업 완료 감지

    const prevTaskCount = useRef(0);
    useEffect(() => {
        if (prevTaskCount.current > 0 && activeTasks.length < prevTaskCount.current) {
            fetchHistory();
            if (viewMode === 'player' && playerData) {
                fetchClips(playerData.video_filename);
                setTimeout(async () => {
                    try {
                        const res = await axios.get(`/api/history?t=${Date.now()}`);
                        const updatedItem = res.data.find(h => h.filename === playerData.video_filename);
                        if (updatedItem) {
                            setPlayerData(prev => ({
                                ...prev,
                                ...updatedItem.result_data,
                                transcripts: prev.transcripts
                            }));
                            // [Fix] 블로그 데이터도 함께 최신화
                            const baseName = playerData.video_filename.split('.')[0];
                            const bRes = await axios.get(`/static/results/${baseName}_blog_view.json?t=${Date.now()}`).catch(() => null);
                            if (bRes) setBlogData(bRes.data);
                        }
                    } catch (e) { console.error("Auto-refresh failed", e); }
                }, 500);
            }
        }
        prevTaskCount.current = activeTasks.length;
    }, [activeTasks, viewMode, playerData]);

    const handleTimeUpdate = () => {
        if (!videoRef.current || !playerData.transcripts) return;
        const currentTime = videoRef.current.currentTime;
        const activeItem = playerData.transcripts.find(
            item => currentTime >= item.start && currentTime <= item.end
        );
        setCurrentSubtitle(activeItem ? activeItem.text : "");
        const index = playerData.transcripts.findIndex(
            item => currentTime >= item.start && currentTime <= item.end
        );
        if (index !== -1 && index !== activeIndex) {
            setActiveIndex(index);
            if (activeTab === 'transcript' && itemRefs.current[index]) {
                itemRefs.current[index].scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        }
    };

    const handleVideoMouseMove = () => {
        setIsControlsVisible(true);
        if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current);
        controlsTimeoutRef.current = setTimeout(() => setIsControlsVisible(false), 2500);
    };

    const handleVideoMouseLeave = () => {
        if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current);
        setIsControlsVisible(false);
    };

    const fetchHistory = async () => {
        try {
            const res = await axios.get(`/api/history?t=${Date.now()}`);
            setHistoryList(res.data);
        } catch (err) { console.error(err); }
    };

    const fetchActiveTasks = async () => {
        try {
            const res = await axios.get(`/api/tasks?t=${Date.now()}`);
            setActiveTasks(res.data);
        } catch (err) { console.error(err); }
    };

    const handleAnalyze = async () => {
        if (!urlInput) return alert("URL을 입력해주세요.");
        setLoading(true);
        try {
            await axios.post('/api/transcribe', {
                url: urlInput,
                custom_title: titleInput
            });
            setUrlInput("");
            setTitleInput("");
            alert("자막 생성 작업이 시작되었습니다.");
            fetchActiveTasks();
        } catch (err) {
            alert("요청 실패: " + err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleStartAnalysis = async (e, filename, title) => {
        if (e) e.stopPropagation();
        if (!confirm(`'${normalizeLegacyTitle(title)}' 영상을 AI로 분석하시겠습니까?
(챕터 구분 및 내용 요약이 진행됩니다)`)) return;
        try {
            await axios.post('/api/analyze', {
                filename: filename,
                custom_title: title
            });
            alert("2단계: AI 분석이 시작되었습니다!");
            fetchActiveTasks();
        } catch (err) {
            alert("요청 실패: " + err.message);
        }
    };

    const handleGenerateBlog = async (e, filename) => {
        if (e) e.stopPropagation();
        if (!confirm(`블로그 포스트를 작성하시겠습니까?
(AI 분석 완료된 챕터가 필요합니다)`)) return;
        try {
            await axios.post('/api/blog/generate', {
                filename: filename
            });
            alert("3단계: 블로그 작성이 시작되었습니다!");
            fetchActiveTasks();
        } catch (err) {
            alert("요청 실패: " + err.message);
        }
    };

    const handleFileUpload = async (file) => {
        if (!file) return;
        setLoading(true);
        try {
            const formData = new FormData();
            formData.append("file", file);
            const upRes = await axios.post('/api/upload', formData);
            await axios.post('/api/transcribe', {
                filename: upRes.data.filename,
                custom_title: titleInput
            });
            setTitleInput("");
            alert("파일 업로드 완료. 자막 생성이 시작됩니다.");
            fetchActiveTasks();
        } catch (err) {
            alert("오류 발생: " + err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (e, filename) => {
        e.stopPropagation();
        if (!confirm("정말로 이 기록을 삭제하시겠습니까? (영상 파일도 함께 삭제됩니다)")) return;
        try {
            await axios.delete(`/api/history/${filename}`);
            fetchHistory();
            if (selectedStudioItem?.filename === filename) {
                setSelectedStudioItem(null);
                setStudioTranscript(null);
            }
        } catch (err) {
            alert("삭제 실패: " + err.message);
        }
    };

    const handleCancelTask = async (taskId) => {
        if (!confirm(`현재 작업을 취소하시겠습니까?
(진행 중인 내용은 저장되지 않습니다)`)) return;
        try {
            await axios.delete(`/api/tasks/${taskId}`);
            fetchActiveTasks();
        } catch (err) {
            alert("취소 요청 실패: " + err.message);
        }
    };

    const loadPlayer = async (item) => {
        try {
            let transcripts = [];
            if (item.result_data.has_transcript_file) {
                const tRes = await axios.get(`/static/results/${item.result_data.transcript_json_filename}?t=${Date.now()}`);
                transcripts = tRes.data;
            }
            const baseName = item.filename.split('.')[0];
            const bRes = await axios.get(`/static/results/${baseName}_blog_view.json?t=${Date.now()}`).catch(() => null);
            if (bRes) setBlogData(bRes.data); else setBlogData(null);
            fetchClips(item.filename);
            setPlayerData({
                ...item.result_data,
                transcripts: transcripts
            });
            setEditTitleText(item.result_data.video_title || item.result_data.video_filename);
            setIsEditingTitle(false);
            setShowSubtitle(true);
            setClipTitle(""); 
            setViewMode('player');
            setActiveTab('chapters');
        } catch (err) {
            console.error("Player load error:", err);
            alert("데이터 로드 실패: 상세 내용은 콘솔을 확인하세요.");
        }
    };

    const handleUpdateTitle = async () => {
        if (!editTitleText.trim()) return alert("제목을 입력해주세요.");
        try {
            await axios.patch(`/api/history/${playerData.video_filename}`, {
                title: editTitleText
            });
            setPlayerData(prev => ({ ...prev, video_title: editTitleText }));
            setIsEditingTitle(false);
            fetchHistory();
        } catch (err) {
            alert("제목 수정 실패: " + err.message);
        }
    };

    const seekVideo = (time) => {
        if (videoRef.current) {
            videoRef.current.currentTime = time;
            videoRef.current.play();
        }
    };
    // [Add] 타임스탬프 링크 클릭을 위해 글로벌 노출
    window.seekFromTimestamp = seekVideo;

    useEffect(() => {
        window.seekFromTimestamp = (seconds) => seekVideo(seconds);
    }, [playerData]);

    const formatTimeSimple = (s) => {
        if (!s && s !== 0) return "0:00";
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0' : ''}${sec}`;
    };

    const setStartToCurrent = () => {
        if (videoRef.current) {
            const t = videoRef.current.currentTime;
            setClipStart(t);
            if (t >= clipEnd) setClipEnd(t + 10);
        }
    };

    const setEndToCurrent = () => {
        if (videoRef.current) {
            const t = videoRef.current.currentTime;
            if (t <= clipStart) {
                alert("종료 시간은 시작 시간보다 뒤여야 합니다.");
                return;
            }
            setClipEnd(t);
        }
    };

    const handleExportClip = async () => {
        if (clipEnd <= clipStart) return alert("구간 설정이 올바르지 않습니다.");
        const finalTitle = clipTitle.trim() || `Clip_${formatTimeSimple(clipStart)}-${formatTimeSimple(clipEnd)}`;
        setIsClipMode(false);
        try {
            await axios.post('/api/export/clip', {
                filename: playerData.video_filename,
                start_time: clipStart,
                end_time: clipEnd,
                title: finalTitle
            });
            alert("클립 생성 작업이 시작되었습니다. 완료되면 아래 보관함에 나타납니다.");
            setClipTitle("");
            fetchActiveTasks();
        } catch (err) {
            console.error(err);
            alert("요청 실패: " + err.message);
        }
    };

    const handleAutoGenerateShorts = async () => {
        const userTopic = prompt(`AI가 숏츠를 제작합니다.

특별히 원하시는 주제나 키워드가 있나요?
(예: '회개', '어린 시절', '다윗')

* 비워두면 AI가 알아서 가장 재미있는 부분을 찾아냅니다.`, "");
        if (userTopic === null) return; 
        try {
            await axios.post('/api/shorts/auto-generate', {
                filename: playerData.video_filename,
                focus_topic: userTopic.trim()
            });
            alert(`AI 숏츠 기획이 시작되었습니다!
(주제: ${userTopic.trim() || '자동 추천'})

우측 하단 작업 모니터에서 진행 상황을 확인하세요.`);
            fetchActiveTasks();
        } catch (err) {
            console.error(err);
            alert("요청 실패: " + err.message);
        }
    };

    const { aiShorts, manualClips } = useMemo(() => {
        const ai = [];
        const manual = [];
        clipsList.forEach(clip => {
            if (clip.is_ai_generated) ai.push(clip);
            else manual.push(clip);
        });
        return { aiShorts: ai, manualClips: manual };
    }, [clipsList]);

    const getOriginalTimeFromShorts = (shortsTime, segments) => {
        if (!segments || segments.length === 0) return 0;
        let remaining = shortsTime;
        for (let seg of segments) {
            const duration = seg.end - seg.start;
            if (remaining <= duration) return seg.start + remaining;
            remaining -= duration;
        }
        return segments[segments.length - 1].end;
    };

    const [activeShortsId, setActiveShortsId] = useState(null);
    const [currentShortsOriginalTime, setCurrentShortsOriginalTime] = useState(0);

    const getShortsTimeFromOriginal = (originalTime, segments) => {
        if (!segments) return 0;
        let accumulatedDuration = 0;
        for (let seg of segments) {
            if (originalTime >= seg.start && originalTime <= seg.end) {
                return accumulatedDuration + (originalTime - seg.start);
            }
            accumulatedDuration += (seg.end - seg.start);
        }
        return 0;
    };

    const handleJumpToShortsScript = (e, videoId, originalTime, segments) => {
        e.stopPropagation();
        e.preventDefault();
        const videoEl = document.getElementById(videoId);
        if (videoEl) {
            const targetShortsTime = getShortsTimeFromOriginal(originalTime, segments);
            videoEl.currentTime = targetShortsTime;
            videoEl.play();
        }
    };

    const [currentShortsSubtitle, setCurrentShortsSubtitle] = useState("");

    const handleShortsTimeUpdate = (e, segments, clipId) => {
        if (!playerData.transcripts) return;
        const currentTime = e.target.currentTime;
        const originalTime = getOriginalTimeFromShorts(currentTime, segments);
        const activeItem = playerData.transcripts.find(
            item => originalTime >= item.start && originalTime <= item.end
        );
        setCurrentShortsSubtitle(activeItem ? activeItem.text : "");
        if (activeShortsId !== clipId) setActiveShortsId(clipId);
        if (Math.abs(currentShortsOriginalTime - originalTime) > 0.5) {
            setCurrentShortsOriginalTime(originalTime);
        }
    };

    useEffect(() => {
        if (activeTab !== 'shorts' || !activeShortsId || !playerData?.transcripts) return;
        const activeIndex = playerData.transcripts.findIndex(
            t => currentShortsOriginalTime >= t.start && currentShortsOriginalTime <= t.end
        );
        if (activeIndex !== -1) {
            const elementId = `shorts-script-item-${activeShortsId}-${activeIndex}`;
            const element = document.getElementById(elementId);
            if (element) {
                const container = element.closest('.shorts-script-container') || element.parentElement;
                if (container) {
                    const elementRect = element.getBoundingClientRect();
                    const containerRect = container.getBoundingClientRect();
                    const relativeTop = elementRect.top - containerRect.top + container.scrollTop;
                    const targetScrollTop = relativeTop - (container.clientHeight / 2) + (element.clientHeight / 2);
                    if (Math.abs(container.scrollTop - targetScrollTop) > 10) {
                        container.scrollTo({ top: targetScrollTop, behavior: 'smooth' });
                    }
                }
            }
        }
    }, [currentShortsOriginalTime, activeShortsId, activeTab, playerData]);

    const handleDownloadSubtitle = async () => {
        const format = prompt("다운로드할 포맷을 입력하세요 (srt, vtt, txt):", "srt");
        if (!format) return;
        const fmt = format.toLowerCase();
        if (!['srt', 'vtt', 'txt'].includes(fmt)) {
            alert("지원하지 않는 포맷입니다. (srt, vtt, txt 중 선택)");
            return;
        }

        const maxCharsStr = prompt("한 줄당 최대 글자 수를 입력하세요 (기본값: 20):", "20");
        const maxChars = parseInt(maxCharsStr) || 20;

        const maxLinesStr = prompt("한 화면당 최대 줄 수를 입력하세요 (기본값: 2):", "2");
        const maxLines = parseInt(maxLinesStr) || 2;

        const removePunc = confirm("문장 부호(.,!? )를 제거하시겠습니까?\n(숏츠 등 깔끔한 자막을 위해 권장됩니다.)");

        try {
            const response = await axios.get(`/api/download/subtitle/${playerData.video_filename}`, {
                params: { 
                    format: fmt, 
                    max_chars: maxChars, 
                    max_lines: maxLines,
                    remove_punctuation: removePunc 
                },
                responseType: 'blob'
            });
            
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            
            let fileName = `${playerData.video_filename.split('.')[0]}_${maxChars}c${maxLines}l${removePunc ? '_nopunc' : ''}.${fmt}`;
            const contentDisposition = response.headers['content-disposition'];
            if (contentDisposition) {
                const fileNameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
                if (fileNameMatch && fileNameMatch.length === 2) fileName = fileNameMatch[1];
            }

            link.setAttribute('download', fileName);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            console.error("Subtitle download failed:", err);
            alert("자막 다운로드 실패: " + err.message);
        }
    };

    // --- Subtitle Studio Logic ---
    const loadStudioTranscript = async (item) => {
        if (!item.result_data.has_transcript_file) {
            if (confirm("이 영상의 자막 데이터가 없습니다. 지금 생성하시겠습니까?")) {
                try {
                    await axios.post('/api/transcribe', { filename: item.filename });
                    alert("자막 생성이 시작되었습니다. 잠시 후 완료되면 다시 선택해주세요.");
                    fetchActiveTasks();
                } catch (e) { alert("요청 실패: " + e.message); }
            }
            return;
        }
        
        setSelectedStudioItem(item);
        try {
            const res = await axios.get(`/static/results/${item.result_data.transcript_json_filename}?t=${Date.now()}`);
            setStudioTranscript(res.data);
        } catch (err) { console.error(err); alert("데이터 로드 실패"); }
    };

    const reflowedStudioSubtitle = useMemo(() => {
        if (!studioTranscript) return [];
        const { maxChars, maxLines, removePunctuation } = studioSettings;
        
        let newSegments = [];
        for (let seg of studioTranscript) {
            let words = seg.words || [];
            if (words.length === 0) {
                let text = seg.text;
                if (removePunctuation) text = text.replace(/[.,?!]/g, "");
                newSegments.push({ start: seg.start, end: seg.end, text: text });
                continue;
            }

            let currentBlockWords = [];
            let currentLines = [];
            let currentLineText = "";

            for (let wordInfo of words) {
                let wordText = wordInfo.word;
                if (removePunctuation) wordText = wordText.replace(/[.,?!]/g, "");
                if (!wordText.trim()) continue;

                let pad = currentLineText.length > 0 ? 1 : 0;
                let predictedLen = currentLineText.length + pad + wordText.length;

                if (predictedLen > maxChars) {
                    if (currentLineText) currentLines.push(currentLineText);
                    currentLineText = wordText;

                    if (currentLines.length >= maxLines) {
                        if (currentBlockWords.length > 0) {
                            newSegments.push({
                                start: currentBlockWords[0].start,
                                end: currentBlockWords[currentBlockWords.length - 1].end,
                                text: currentLines.join("\n")
                            });
                        }
                        currentLines = [];
                        currentBlockWords = [];
                    }
                } else {
                    currentLineText = currentLineText ? (currentLineText + " " + wordText) : wordText;
                }
                currentBlockWords.push(wordInfo);
            }

            if (currentLineText) currentLines.push(currentLineText);
            if (currentLines.length > 0 && currentBlockWords.length > 0) {
                newSegments.push({
                    start: currentBlockWords[0].start,
                    end: currentBlockWords[currentBlockWords.length - 1].end,
                    text: currentLines.join("\n")
                });
            }
        }
        return newSegments;
    }, [studioTranscript, studioSettings]);

    const handleStudioDownload = async (format) => {
        if (!selectedStudioItem) return;
        try {
            const response = await axios.get(`/api/download/subtitle/${selectedStudioItem.filename}`, {
                params: { 
                    format: format, 
                    max_chars: studioSettings.maxChars, 
                    max_lines: studioSettings.maxLines,
                    remove_punctuation: studioSettings.removePunctuation 
                },
                responseType: 'blob'
            });
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `${selectedStudioItem.title.replace(/\s+/g, '_')}_studio.${format}`);
            document.body.appendChild(link);
            link.click();
            link.remove();
        } catch (err) { alert("다운로드 실패: " + err.message); }
    };

    return (
        <div className="flex flex-col h-screen overflow-hidden">
            <header className="shrink-0 bg-white border-b py-4 px-6 shadow-sm z-30">
                <div className="max-w-7xl mx-auto flex justify-between items-center w-full relative">
                    <h1 onClick={() => { setViewMode('dashboard'); setDashboardTab('analysis'); }}
                        className="text-2xl font-bold text-indigo-600 flex items-center gap-2 cursor-pointer hover:opacity-80 transition shrink-0">
                        🤖 AI Video Analyst
                    </h1>
                    
                    {/* Centered Segmented Control */} 
                    {viewMode === 'dashboard' && (
                        <div className="absolute left-1/2 -translate-x-1/2">
                            <SegmentedControl 
                                activeTab={dashboardTab} 
                                onChange={setDashboardTab} 
                            />
                        </div>
                    )}

                    <div className="flex items-center gap-3 shrink-0">
                        <button 
                            onClick={() => setIsSettingsOpen(true)}
                            className="text-gray-400 hover:text-indigo-600 transition p-2 rounded-full hover:bg-indigo-50"
                            title="설정"
                        >
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                        </button>
                        
                        {viewMode === 'player' && (
                            <button onClick={() => setViewMode('dashboard')} className="text-sm font-bold text-gray-500 hover:text-indigo-600 flex items-center gap-1">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
                                대시보드로 나가기
                            </button>
                        )}
                    </div>
                </div>
            </header>

            <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
            <TaskMonitor tasks={activeTasks} onCancel={handleCancelTask} />

            <main className="flex-1 flex overflow-hidden bg-gray-50">
                {/* --- View 1: Dashboard --- */} 
                {viewMode === 'dashboard' && (
                    <div className="w-full h-full flex flex-col overflow-hidden">
                        {/* Tab Content Switching */} 
                        {dashboardTab === 'analysis' ? (
                            <div className="w-full h-full overflow-y-auto custom-scrollbar">
                                <div className="max-w-6xl mx-auto p-4 md:p-8 fade-in space-y-12">
                                    {/* System Update Banner */} 
                                    {updateAvailable && (
                                        <div className="bg-indigo-600 rounded-2xl p-4 mb-8 text-white shadow-lg flex flex-col md:flex-row justify-between items-center gap-4 animate-bounce-subtle">
                                            <div className="flex items-center gap-3">
                                                <div className="bg-indigo-500 p-2 rounded-full">
                                                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.001 0 01-15.357-2m15.357 2H15"></path></svg>
                                                </div>
                                                <div>
                                                    <h4 className="font-bold text-sm">새로운 시스템 업데이트가 있습니다!</h4>
                                                    <p className="text-xs text-indigo-100">현재: {updateInfo.current_version} → 최신: {updateInfo.latest_version}</p>
                                                </div>
                                            </div>
                                            <button 
                                                onClick={handleSystemUpdate}
                                                disabled={isUpdating}
                                                className="bg-white text-indigo-600 px-6 py-2 rounded-xl font-bold text-sm hover:bg-indigo-50 transition shadow-sm disabled:opacity-50"
                                            >
                                                {isUpdating ? '업데이트 중...' : '🚀 지금 업데이트'}
                                            </button>
                                        </div>
                                    )}

                                    {/* Input Section */} 
                                    <section className="bg-white p-8 rounded-2xl shadow-sm border border-gray-200">
                                        <h2 className="text-xl font-bold text-gray-800 mb-6 text-center">새 영상 분석하기</h2>
                                        <div className="max-w-2xl mx-auto space-y-6">
                                            <div className="flex gap-3">
                                                <input type="text" placeholder="YouTube URL을 입력하세요..." className="flex-1 p-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none transition" value={urlInput} onChange={(e) => setUrlInput(e.target.value)} disabled={loading} />
                                            </div>
                                            <div>
                                                <input type="text" placeholder="영상 제목을 미리 설정할 수 있습니다 (선택사항)" className="w-full p-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none transition text-sm" value={titleInput} onChange={(e) => setTitleInput(e.target.value)} disabled={loading} />
                                                <p className="text-xs text-gray-400 mt-1 ml-1">* 비워두면 유튜브 제목이나 파일명을 그대로 사용합니다.</p>
                                            </div>
                                            <div className="flex gap-4">
                                                <button onClick={handleAnalyze} disabled={loading} className="flex-1 bg-indigo-600 text-white px-6 py-3 rounded-xl font-bold hover:bg-indigo-700 disabled:bg-gray-400 transition shadow-md">{loading ? "분석 요청 중..." : "🚀 URL 분석 시작"}</button>
                                            </div>
                                            <div className="relative flex py-2 items-center">
                                                <div className="flex-grow border-t border-gray-200"></div>
                                                <span className="flex-shrink-0 mx-4 text-gray-400 text-xs">OR</span>
                                                <div className="flex-grow border-t border-gray-200"></div>
                                            </div>
                                            <label className="block w-full cursor-pointer bg-gray-50 border-2 border-dashed border-gray-300 rounded-xl p-4 text-center hover:bg-indigo-50 transition group">
                                                <span className="text-gray-500 group-hover:text-indigo-600 font-medium">📁 로컬 MP4 파일 업로드 (제목 입력 후 선택)</span>
                                                <input type="file" accept="video/mp4" className="hidden" onChange={(e) => handleFileUpload(e.target.files[0])} />
                                            </label>
                                        </div>
                                    </section>

                                    <section>
                                        <h3 className="text-lg font-bold text-gray-700 mb-4 flex items-center gap-2">📚 내 작업 목록 <span className="bg-gray-200 text-gray-600 text-xs px-2 py-0.5 rounded-full">{historyList.length}</span></h3>
                                        {historyList.length === 0 ? (
                                            <div className="text-center py-12 text-gray-400 bg-white rounded-xl border border-dashed">아직 작업된 영상이 없습니다.</div>
                                        ) : (
                                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 pb-10">
                                                {historyList.map((item, idx) => {
                                                    const hasChapters = item.total_chapters > 0;
                                                    const hasBlog = hasChapters && item.result_data.chapters.some(c => c.blog_content);
                                                    return (
                                                        <div key={idx} onClick={() => loadPlayer(item)} className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 cursor-pointer hover:shadow-md hover:border-indigo-300 transition group relative overflow-hidden flex flex-col">
                                                            <div className="absolute top-0 left-0 w-1 h-full bg-indigo-500 opacity-0 group-hover:opacity-100 transition"></div>
                                                            <button onClick={(e) => handleDelete(e, item.filename)} className="absolute top-4 right-4 text-gray-300 hover:text-red-500 transition p-1 z-10"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
                                                            <div className="flex flex-col mb-4">
                                                                <h4 className="font-bold text-gray-800 line-clamp-2 mb-1 group-hover:text-indigo-600 transition">{normalizeLegacyTitle(item.title)}</h4>
                                                                <p className="text-[10px] text-gray-400">{new Date(item.timestamp * 1000).toLocaleString()}</p>
                                                            </div>
                                                            <div className="flex flex-wrap gap-1.5 mb-4">
                                                                <span className="text-[9px] font-bold bg-green-100 text-green-700 px-1.5 py-0.5 rounded border border-green-200 uppercase tracking-tighter">자막 완료</span>
                                                                {hasChapters ? <span className="text-[9px] font-bold bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded border border-blue-200 uppercase tracking-tighter">분석 완료</span> : <span className="text-[9px] font-bold bg-gray-100 text-gray-400 px-1.5 py-0.5 rounded border border-gray-200 uppercase tracking-tighter">분석 대기</span>}
                                                                {hasBlog && <span className="text-[9px] font-bold bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded border border-purple-200 uppercase tracking-tighter">블로그 완료</span>}
                                                            </div>
                                                            <div className="mt-auto grid grid-cols-2 gap-2 pt-3 border-t border-gray-50">
                                                                <button onClick={(e) => handleStartAnalysis(e, item.filename, item.title)} className={`text-[11px] font-bold py-2 rounded transition flex items-center justify-center gap-1 shadow-sm ${hasChapters ? 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100' : 'bg-indigo-600 text-white hover:bg-indigo-700'}`}>{hasChapters ? '🔄 2. 재분석' : '✨ 2. AI 분석'}</button>
                                                                <button onClick={(e) => hasChapters ? handleGenerateBlog(e, item.filename) : alert('먼저 AI 분석을 완료해주세요.')} disabled={!hasChapters} className={`text-[11px] font-bold py-2 rounded transition flex items-center justify-center gap-1 shadow-sm ${hasChapters ? 'bg-purple-50 text-purple-600 hover:bg-purple-100' : 'bg-gray-50 text-gray-300 cursor-not-allowed'}`}>{hasBlog ? '🔄 3. 재작성' : '📝 3. 블로그'}</button>
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </section>
                                </div>
                            </div>
                        ) : (
                            /* Subtitle Studio Tab Content */
                            <div className="flex-1 flex overflow-hidden">
                                {/* Left Sidebar: Work List & Upload */} 
                                <aside className="w-1/3 border-r bg-white flex flex-col overflow-hidden">
                                    <div className="p-4 border-b space-y-4">
                                        <button 
                                            onClick={() => setIsUploadPanelOpen(!isUploadPanelOpen)}
                                            className="w-full bg-indigo-600 text-white py-2 rounded-xl font-bold flex items-center justify-center gap-2 hover:bg-indigo-700 transition shadow-sm"
                                        >
                                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                                            새 작업 추가
                                        </button>

                                        {isUploadPanelOpen && (
                                            <div className="bg-gray-50 p-4 rounded-xl border border-indigo-100 space-y-3 animate-fade-in">
                                                <input 
                                                    type="text" 
                                                    placeholder="YouTube URL..."
                                                    className="w-full p-2 text-sm border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none"
                                                    value={urlInput}
                                                    onChange={(e) => setUrlInput(e.target.value)}
                                                />
                                                <div className="flex gap-2">
                                                    <button 
                                                        onClick={handleAnalyze}
                                                        className="flex-1 bg-indigo-100 text-indigo-700 py-1.5 rounded-lg text-xs font-bold hover:bg-indigo-200 transition"
                                                    >
                                                        URL 추가
                                                    </button>
                                                    <label className="flex-1 bg-white border border-gray-300 py-1.5 rounded-lg text-xs font-bold text-gray-600 text-center cursor-pointer hover:bg-gray-50 transition">
                                                        파일 업로드
                                                        <input type="file" accept="video/mp4" className="hidden" onChange={(e) => handleFileUpload(e.target.files[0])} />
                                                    </label>
                                                </div>
                                            </div>
                                        )}

                                        <div className="relative">
                                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                                            </span>
                                            <input 
                                                type="text" 
                                                placeholder="제목 검색..."
                                                className="w-full pl-9 pr-4 py-2 bg-gray-100 border-0 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
                                                value={studioSearch}
                                                onChange={(e) => setStudioSearch(e.target.value)}
                                            />
                                        </div>
                                    </div>

                                    <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
                                        {historyList
                                            .filter(item => item.title.toLowerCase().includes(studioSearch.toLowerCase()))
                                            .map((item, idx) => {
                                                const isSelected = selectedStudioItem?.filename === item.filename;
                                                const hasTranscript = item.result_data.has_transcript_file;
                                                const isProcessing = activeTasks.some(t => t.filename === item.filename && t.type === 'transcription');

                                                return (
                                                    <div 
                                                        key={idx} 
                                                        onClick={() => loadStudioTranscript(item)}
                                                        className={`p-3 rounded-xl cursor-pointer transition flex justify-between items-center group ${isSelected ? 'bg-indigo-50 border border-indigo-200' : 'hover:bg-gray-50 border border-transparent'}`}
                                                    >
                                                        <div className="overflow-hidden">
                                                            <h4 className={`text-sm font-bold truncate ${isSelected ? 'text-indigo-700' : 'text-gray-700'}`}>{normalizeLegacyTitle(item.title)}</h4>
                                                            <div className="flex items-center gap-2 mt-1">
                                                                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${hasTranscript ? 'bg-green-100 text-green-600' : isProcessing ? 'bg-indigo-100 text-indigo-600 animate-pulse' : 'bg-gray-100 text-gray-400'}`}>
                                                                    {hasTranscript ? '✅ 자막완료' : isProcessing ? '🔄 생성중' : '⚠️ 자막없음'}
                                                                </span>
                                                                <span className="text-[10px] text-gray-400">{new Date(item.timestamp * 1000).toLocaleDateString()}</span>
                                                            </div>
                                                        </div>
                                                        <button onClick={(e) => handleDelete(e, item.filename)} className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-300 hover:text-red-500 transition"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
                                                    </div>
                                                );
                                            })}
                                    </div>
                                </aside>

                                {/* Right Main: Subtitle Studio Workspace */} 
                                <section className="flex-1 bg-gray-50 flex flex-col overflow-hidden relative">
                                    {!selectedStudioItem ? (
                                        <div className="flex-1 flex flex-col items-center justify-center text-gray-400 text-center p-8">
                                            <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-200 mb-4 text-6xl">🎞️</div>
                                            <h3 className="text-xl font-bold text-gray-600 mb-2">자막 스튜디오에 오신 것을 환영합니다!</h3>
                                            <p className="max-w-xs leading-relaxed">왼쪽 목록에서 영상을 선택하여 자막 가공을 시작하세요.<br/>자막이 없는 경우 자동으로 생성을 요청합니다.</p>
                                        </div>
                                    ) : (
                                        <div className="flex-1 flex flex-col overflow-hidden">
                                            {/* Studio Header */} 
                                            <div className="bg-white p-6 border-b shadow-sm shrink-0">
                                                <div className="flex justify-between items-start mb-6">
                                                    <div>
                                                        <h2 className="text-xl font-bold text-gray-800 mb-1">{normalizeLegacyTitle(selectedStudioItem.title)}</h2>
                                                        <p className="text-sm text-gray-400">자막 블록 수: {reflowedStudioSubtitle.length}개</p>
                                                    </div>
                                                    <div className="flex gap-2">
                                                        <button onClick={() => handleStudioDownload('srt')} className="bg-indigo-600 text-white px-4 py-2 rounded-xl font-bold text-sm hover:bg-indigo-700 transition shadow-md flex items-center gap-2">
                                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                                                            SRT 다운로드
                                                        </button>
                                                        <button onClick={() => handleStudioDownload('vtt')} className="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded-xl font-bold text-sm hover:bg-gray-50 transition shadow-sm">VTT</button>
                                                        <button onClick={() => handleStudioDownload('txt')} className="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded-xl font-bold text-sm hover:bg-gray-50 transition shadow-sm">TXT</button>
                                                    </div>
                                                </div>

                                                {/* Studio Controls */} 
                                                <div className="grid grid-cols-1 md:grid-cols-3 gap-8 bg-gray-50 p-5 rounded-2xl border border-gray-100">
                                                    <div className="space-y-3">
                                                        <div className="flex justify-between items-center">
                                                            <label className="text-xs font-bold text-gray-500 uppercase tracking-wider">📏 한 줄당 최대 글자 수</label>
                                                            <span className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded text-sm font-mono font-bold">{studioSettings.maxChars}자</span>
                                                        </div>
                                                        <input 
                                                            type="range" min="5" max="50" step="1" 
                                                            className="w-full accent-indigo-600"
                                                            value={studioSettings.maxChars}
                                                            onChange={(e) => setStudioStudioSettings(prev => ({...prev, maxChars: parseInt(e.target.value)}))}
                                                        />
                                                        <div className="flex justify-between text-[10px] text-gray-400 font-mono"><span>5자</span><span>50자</span></div>
                                                    </div>

                                                    <div className="space-y-3">
                                                        <label className="text-xs font-bold text-gray-500 uppercase tracking-wider block">≣ 최대 표시 줄 수</label>
                                                        <div className="flex bg-white p-1 rounded-xl border border-gray-200">
                                                            {[1, 2, 3, 4].map(num => (
                                                                <button 
                                                                    key={num}
                                                                    onClick={() => setStudioStudioSettings(prev => ({...prev, maxLines: num}))}
                                                                    className={`flex-1 py-1.5 rounded-lg text-sm font-bold transition ${studioSettings.maxLines === num ? 'bg-indigo-600 text-white shadow-sm' : 'text-gray-400 hover:text-gray-600'}`}
                                                                >
                                                                    {num}줄
                                                                </button>
                                                            ))}
                                                        </div>
                                                    </div>

                                                    <div className="flex items-center gap-3 h-full">
                                                        <div className="flex-1 bg-white p-3 rounded-xl border border-gray-200 flex justify-between items-center">
                                                            <span className="text-xs font-bold text-gray-500">✨ 문장 부호 제거</span>
                                                            <button 
                                                                onClick={() => setStudioStudioSettings(prev => ({...prev, removePunctuation: !prev.removePunctuation}))}
                                                                className={`w-12 h-6 rounded-full transition-all relative ${studioSettings.removePunctuation ? 'bg-indigo-600' : 'bg-gray-300'}`}
                                                            >
                                                                <div className={`absolute top-1 bg-white w-4 h-4 rounded-full transition-all ${studioSettings.removePunctuation ? 'left-7' : 'left-1'}`}></div>
                                                            </button>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Preview List */} 
                                            <div className="flex-1 overflow-y-auto p-6 space-y-4 custom-scrollbar bg-white/50">
                                                <div className="max-w-2xl mx-auto space-y-4">
                                                    <h3 className="text-sm font-bold text-gray-400 uppercase tracking-widest flex items-center gap-2 mb-6">
                                                        <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                                                        Live Preview
                                                    </h3>
                                                    {reflowedStudioSubtitle.length === 0 ? (
                                                        <div className="py-20 text-center text-gray-400 animate-pulse">데이터를 처리 중입니다...</div>
                                                    ) : (
                                                        reflowedStudioSubtitle.map((seg, idx) => (
                                                            <div key={idx} className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 group hover:border-indigo-200 transition-all">
                                                                <div className="flex items-center gap-3 mb-3">
                                                                    <span className="text-[10px] font-bold text-white bg-gray-300 px-2 py-0.5 rounded-full">{idx + 1}</span>
                                                                    <span className="text-xs font-mono text-indigo-400 font-bold">{formatTimeSimple(seg.start)} → {formatTimeSimple(seg.end)}</span>
                                                                </div>
                                                                <p className="text-gray-800 text-lg leading-relaxed whitespace-pre-wrap font-medium">
                                                                    {seg.text}
                                                                </p>
                                                            </div>
                                                        ))
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </section>
                            </div>
                        )}
                    </div>
                )}

                {viewMode === 'player' && playerData && (
                    <div className="w-full h-full flex flex-col lg:flex-row max-w-7xl mx-auto fade-in bg-white shadow-xl overflow-hidden">
                        <div className="w-full lg:w-5/12 h-full flex flex-col border-r border-gray-200 bg-white relative z-10">
                            <div className="flex-1 overflow-y-auto p-4 lg:p-6 custom-scrollbar">
                                <div className="bg-black rounded-xl overflow-hidden shadow-lg aspect-video relative group sticky top-0 z-20" onMouseMove={handleVideoMouseMove} onMouseLeave={handleVideoMouseLeave}>
                                    <video ref={videoRef} controls playsInline preload="metadata" crossOrigin="anonymous" className="w-full h-full object-contain" onTimeUpdate={handleTimeUpdate} onLoadedMetadata={(e) => setTotalDuration(e.target.duration)} onPlay={() => { if (!activeShortsId) setCurrentShortsSubtitle(""); }}>
                                        <source src={`/api/stream/video/${playerData.video_filename}`} type="video/mp4" />
                                        {playerData.vtt_filename && <track kind="subtitles" src={`/static/results/${playerData.vtt_filename}`} srcLang="ko" label="한국어" default={false} />}
                                    </video>
                                    {showSubtitle && currentSubtitle && (
                                        <div className={`absolute left-0 w-full text-center px-4 pointer-events-none transition-all duration-300 ease-in-out z-10 ${isControlsVisible ? 'bottom-16' : 'bottom-4'}`}>
                                            <span className="inline-block bg-black/30 text-white text-xs md:text-base px-1 py-0.25 rounded-lg leading-relaxed shadow-sm backdrop-blur-sm">{removePunctuation(currentSubtitle)}</span>
                                        </div>
                                    )}
                                </div>
                                <div className="mt-4 space-y-4">
                                    <div className="flex justify-end gap-2">
                                        <button onClick={handleDownloadOriginalVideo} className="px-3 py-1.5 text-xs font-bold rounded-lg border flex items-center gap-2 transition bg-indigo-50 text-indigo-600 border-indigo-200 hover:bg-indigo-100" title="원본 영상 파일 다운로드">
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                                            원본 영상 다운로드
                                        </button>
                                        <button onClick={() => setShowSubtitle(!showSubtitle)} className={`px-3 py-1.5 text-xs font-bold rounded-lg border flex items-center gap-2 transition ${showSubtitle ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}>
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"></path></svg>
                                            {showSubtitle ? '자막 끄기' : '자막 켜기'}
                                        </button>
                                    </div>
                                    <div className="bg-gray-50 p-4 rounded-xl border border-gray-100">
                                        <div className="flex items-start justify-between gap-2 mb-2">
                                            {isEditingTitle ? (
                                                <div className="flex-1 flex gap-2">
                                                    <input type="text" className="flex-1 p-2 border border-indigo-300 rounded focus:outline-none focus:ring-2 focus:ring-indigo-500 text-lg font-bold" value={editTitleText} onChange={(e) => setEditTitleText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleUpdateTitle()} />
                                                    <button onClick={handleUpdateTitle} className="bg-indigo-600 text-white px-3 rounded font-bold text-sm hover:bg-indigo-700">저장</button>
                                                    <button onClick={() => setIsEditingTitle(false)} className="bg-gray-300 text-gray-700 px-3 rounded font-bold text-sm hover:bg-gray-400">취소</button>
                                                </div>
                                            ) : (
                                                <h2 className="font-bold text-gray-800 text-lg leading-snug flex-1">{normalizeLegacyTitle(playerData.video_title || playerData.chapters[0]?.title || "제목 없음")}</h2>
                                            )}
                                            {!isEditingTitle && <button onClick={() => setIsEditingTitle(true)} className="text-gray-400 hover:text-indigo-600 p-1" title="제목 수정"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg></button>}
                                        </div>
                                        <p className="text-sm text-gray-500">AI 분석 완료 • {playerData.total_chapters}개의 챕터</p>
                                    </div>
                                    <div>
                                        {!isClipMode ? (
                                            <button onClick={() => { setIsClipMode(true); if (videoRef.current) { const t = videoRef.current.currentTime; setClipStart(t); setClipEnd(t + 10); } }} className="w-full py-3 border-2 border-dashed border-indigo-200 rounded-xl text-indigo-500 font-bold hover:bg-indigo-50 hover:border-indigo-400 transition flex items-center justify-center gap-2">
                                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243 4.243 3 3 0 004.243-4.243zm0-5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z"></path></svg>
                                                ✂️ 구간 잘라서 내보내기
                                            </button>
                                        ) : (
                                            <div className="bg-white border-2 border-indigo-500 rounded-xl p-5 shadow-lg animate-fade-in relative overflow-hidden">
                                                <div className="flex justify-between items-center mb-2">
                                                    <h3 className="font-bold text-gray-800 flex items-center gap-2"><span className="bg-indigo-600 text-white text-xs px-2 py-1 rounded">REC</span>구간 자르기</h3>
                                                    <button onClick={() => setIsClipMode(false)} className="text-gray-400 hover:text-red-500"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
                                                </div>
                                                <TimelineVisualizer totalDuration={totalDuration} start={clipStart} end={clipEnd} />
                                                <div className="grid grid-cols-2 gap-4 mb-4 mt-4">
                                                    <div className="bg-gray-50 p-3 rounded-xl border border-gray-200">
                                                        <label className="text-xs text-gray-500 font-bold mb-1 block">시작 (Start)</label>
                                                        <div className="text-xl font-mono font-bold text-indigo-600 tracking-tight mb-2">{formatTimeDetail(clipStart)}</div>
                                                        <input type="number" step="0.1" className="w-full p-1.5 text-xs bg-white border border-gray-300 rounded outline-none" value={clipStart} onChange={(e) => setClipStart(parseFloat(e.target.value))} />
                                                        <button onClick={setStartToCurrent} className="w-full mt-2 py-1.5 bg-white border border-gray-300 rounded text-xs font-bold text-gray-600 hover:text-indigo-600 transition">📍 현재 위치</button>
                                                    </div>
                                                    <div className="bg-gray-50 p-3 rounded-xl border border-gray-200">
                                                        <label className="text-xs text-gray-500 font-bold mb-1 block">종료 (End)</label>
                                                        <div className="text-xl font-mono font-bold text-indigo-600 tracking-tight mb-2">{formatTimeDetail(clipEnd)}</div>
                                                        <input type="number" step="0.1" className="w-full p-1.5 text-xs bg-white border border-gray-300 rounded outline-none" value={clipEnd} onChange={(e) => setClipEnd(parseFloat(e.target.value))} />
                                                        <button onClick={setEndToCurrent} className="w-full mt-2 py-1.5 bg-white border border-gray-300 rounded text-xs font-bold text-gray-600 hover:text-indigo-600 transition">📍 현재 위치</button>
                                                    </div>
                                                </div>
                                                <div className="mb-4">
                                                    <input type="text" placeholder="클립 제목 (선택사항)" className="w-full p-2 border border-gray-300 rounded focus:ring-2 focus:ring-indigo-500 outline-none text-sm" value={clipTitle} onChange={(e) => setClipTitle(e.target.value)} />
                                                </div>
                                                <div className="flex gap-2">
                                                    <button onClick={() => { if (videoRef.current) { videoRef.current.currentTime = clipStart; videoRef.current.play(); } }} className="flex-1 py-2 bg-gray-100 text-gray-700 rounded-lg font-bold text-xs hover:bg-gray-200 flex items-center justify-center gap-1">▶ 미리보기</button>
                                                    <button onClick={handleExportClip} className="flex-[2] py-2 bg-indigo-600 text-white rounded-lg font-bold text-xs hover:bg-indigo-700 shadow-md flex items-center justify-center gap-1">내보내기</button>
                                                </div>
                                            </div>
                                        )}
                                        {clipsList.length > 0 && (
                                            <div className="mt-6 animate-fade-in">
                                                <h3 className="font-bold text-gray-700 mb-2 flex items-center gap-2 text-sm">📂 클립 보관함 <span className="bg-gray-200 text-gray-600 text-xs px-2 py-0.5 rounded-full">{clipsList.length}</span></h3>
                                                <div className="space-y-2 max-h-48 overflow-y-auto pr-1 custom-scrollbar">
                                                    {clipsList.map((clip) => (
                                                        <div key={clip.clip_id} className="bg-white border border-gray-200 rounded p-3 flex justify-between items-center shadow-sm hover:shadow-md transition text-sm">
                                                            <div className="flex flex-col overflow-hidden mr-2">
                                                                <span className="font-bold text-gray-800 truncate" title={clip.title}>{clip.title}</span>
                                                                <span className="text-xs text-gray-500 font-mono">
                                                                    {(clip.is_ai_generated || clip.duration) ? (
                                                                        <span>Total: {clip.duration ? clip.duration.toFixed(1) : "0.0"}s</span>
                                                                    ) : (
                                                                        <span>{formatTimeSimple(clip.start_time)} ~ {formatTimeSimple(clip.end_time)} ({(clip.end_time - clip.start_time).toFixed(1)}s)</span>
                                                                    )}
                                                                </span>
                                                            </div>
                                                            <div className="flex items-center gap-1 shrink-0">
                                                                <a href={clip.download_url} download className="p-1.5 bg-indigo-50 text-indigo-600 rounded hover:bg-indigo-100 transition"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg></a>
                                                                <button onClick={() => handleDeleteClip(clip.clip_id)} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="w-full lg:w-7/12 h-full bg-gray-50 flex flex-col overflow-hidden">
                            <div className="flex border-b border-gray-200 bg-white shrink-0 z-30">
                                <button onClick={() => setActiveTab('shorts')} className={`flex-1 py-4 text-sm font-bold transition-all border-b-2 ${activeTab === 'shorts' ? 'border-indigo-600 text-indigo-600 bg-indigo-50/50' : 'border-transparent text-gray-400 hover:text-gray-600'}`}>⚡ AI 숏츠</button>
                                <button onClick={() => setActiveTab('chapters')} className={`flex-1 py-4 text-sm font-bold transition-all border-b-2 ${activeTab === 'chapters' ? 'border-indigo-600 text-indigo-600 bg-indigo-50/50' : 'border-transparent text-gray-400 hover:text-gray-600'}`}>요약 노트</button>
                                <button onClick={() => setActiveTab('blog')} className={`flex-1 py-4 text-sm font-bold transition-all border-b-2 ${activeTab === 'blog' ? 'border-indigo-600 text-indigo-600 bg-indigo-50/50' : 'border-transparent text-gray-400 hover:text-gray-600'}`}>블로그 뷰</button>
                                <button onClick={() => setActiveTab('transcript')} className={`flex-1 py-4 text-sm font-bold transition-all border-b-2 ${activeTab === 'transcript' ? 'border-indigo-600 text-indigo-600 bg-indigo-50/50' : 'border-transparent text-gray-400 hover:text-gray-600'}`}>스크립트</button>
                            </div>
                            {activeTab === 'chapters' && (
                                <div className="flex justify-end gap-2 px-6 py-3 bg-gray-50 border-b border-gray-200 shrink-0 z-20 shadow-sm">
                                    <button onClick={() => setAllChapters(true)} className="text-xs font-bold text-indigo-600 bg-white border border-indigo-100 px-3 py-1.5 rounded-lg hover:bg-indigo-50 hover:border-indigo-300 transition flex items-center gap-1 shadow-sm"><svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 13l-7 7-7-7m14-8l-7 7-7-7"></path></svg>모두 펼치기</button>
                                    <button onClick={() => setAllChapters(false)} className="text-xs font-bold text-gray-500 bg-white border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-100 hover:text-gray-700 transition flex items-center gap-1 shadow-sm"><svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 11l7-7 7 7m-14 8l7-7 7 7"></path></svg>모두 접기</button>
                                </div>
                            )}
                            <div className="flex-1 overflow-y-auto p-4 lg:p-8 custom-scrollbar scroll-smooth relative">
                                {activeTab === 'shorts' && (
                                    <div className="p-6 md:p-8 pb-20 space-y-8 animate-fade-in">
                                        <div className="bg-gradient-to-r from-indigo-500 to-purple-600 rounded-2xl p-8 text-white shadow-lg relative overflow-hidden">
                                            <div className="absolute top-0 right-0 w-64 h-64 bg-white opacity-10 rounded-full transform translate-x-20 -translate-y-20 blur-3xl"></div>
                                            <div className="relative z-10">
                                                <h2 className="text-2xl font-bold mb-2 flex items-center gap-2">⚡ AI Auto Shorts</h2>
                                                <p className="text-indigo-100 mb-6 max-w-lg leading-relaxed">긴 영상에서 가장 반응이 좋을 만한 핵심 구간을 AI가 자동으로 찾아내고, 지루한 부분은 덜어내어(Jump Cut) 1분 미만의 숏츠로 만들어 드립니다.</p>
                                                <button onClick={handleAutoGenerateShorts} className="bg-white text-indigo-600 font-bold px-6 py-3 rounded-xl shadow-md hover:bg-gray-50 hover:scale-105 transition transform flex items-center gap-2"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>지금 자동 생성하기</button>
                                            </div>
                                        </div>
                                        <div>
                                            <h3 className="font-bold text-gray-800 text-lg mb-4 flex items-center gap-2">🎬 생성된 숏츠 목록 <span className="text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded text-sm">{aiShorts.length}</span></h3>
                                            {aiShorts.length === 0 ? (
                                                <div className="text-center py-12 border-2 border-dashed border-gray-200 rounded-xl bg-gray-50 text-gray-400">아직 생성된 AI 숏츠가 없습니다.<br />위 버튼을 눌러보세요!</div>
                                            ) : (
                                                <div className="grid grid-cols-1 gap-6">
                                                    {aiShorts.map((clip, idx) => {
                                                        const safeId = clip.clip_id || clip.shorts_id;
                                                        const uniqueKey = safeId || `fallback-idx-${idx}`;
                                                        const videoElementId = `shorts-video-${uniqueKey}`;
                                                        const createdDate = clip.created_at ? new Date(clip.created_at).toLocaleString('ko-KR') : "날짜 정보 없음";
                                                        return (
                                                            <details key={uniqueKey} className="group/item bg-white border border-gray-200 rounded-xl shadow-sm open:border-indigo-300 open:shadow-md transition overflow-hidden">
                                                                <summary className="p-5 flex justify-between items-start cursor-pointer list-none select-none bg-white hover:bg-gray-50 transition">
                                                                    <div className="flex-1">
                                                                        <div className="flex items-center gap-2 mb-2"><span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold bg-purple-100 text-purple-600 border border-purple-200">AI SHORTS</span><span className="text-xs text-gray-400">{createdDate}</span></div>
                                                                        <h4 className="font-bold text-gray-900 text-lg group-open/item:text-indigo-600 transition flex items-center gap-2">{clip.title}<svg className="w-4 h-4 text-gray-400 transform group-open/item:rotate-180 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg></h4>
                                                                        <div className="flex flex-wrap gap-2 mt-2">{clip.segments && clip.segments.map((seg, sIdx) => (<span key={sIdx} className="text-xs font-mono bg-gray-100 text-gray-600 px-2 py-0.5 rounded border border-gray-200">{formatTimeSimple(seg.start)}~{formatTimeSimple(seg.end)}</span>))}<span className="text-xs font-bold text-indigo-500 self-center">총 {clip.duration ? clip.duration.toFixed(1) : 0}초</span></div>
                                                                    </div>
                                                                    <div className="flex gap-2 shrink-0 ml-4">
                                                                        <button onClick={(e) => handleExportPremiere(e, safeId)} className="px-4 py-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition font-bold text-sm flex items-center gap-2 shadow-md" title="프리미어 프로용 패키지(XML + 자막) 다운로드">
                                                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"></path></svg>
                                                                            프리미어 프로 패키지 내보내기
                                                                        </button>
                                                                        <button onClick={(e) => { e.preventDefault(); handleDeleteClip(safeId); }} className="p-2 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition" title="삭제"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
                                                                    </div>
                                                                </summary>
                                                                <div className="p-5 border-t border-gray-100 bg-gray-50/50 flex flex-col gap-6 animate-fade-in">
                                                                    <div className="w-full bg-black rounded-xl overflow-hidden shadow-lg relative flex justify-center bg-zinc-900 group">
                                                                        {clip.preview_url ? (
                                                                            <>
                                                                                <video id={videoElementId} controls crossOrigin="anonymous" className="w-full max-h-[500px] object-contain" onTimeUpdate={(e) => handleShortsTimeUpdate(e, clip.segments, uniqueKey)} onPlay={() => { setCurrentShortsSubtitle(""); setActiveShortsId(uniqueKey); }}>
                                                                                    <source src={clip.preview_url} type="video/mp4" />
                                                                                    {clip.filename_vtt && <track kind="subtitles" src={`/static/clips/${clip.filename_vtt}`} srcLang="ko" label="한국어" />}
                                                                                </video>
                                                                                {currentShortsSubtitle && <div className="absolute left-0 w-full text-center px-4 pointer-events-none transition-all duration-300 ease-in-out z-20 bottom-4 group-hover:bottom-16"><span className="inline-block bg-black/30 text-white text-xs md:text-base px-1 py-0.25 rounded-lg leading-relaxed shadow-sm">{removePunctuation(currentShortsSubtitle)}</span></div>}
                                                                            </>
                                                                        ) : (<div className="flex items-center justify-center h-64 w-full text-gray-500 text-sm">미리보기 파일 없음</div>)}
                                                                    </div>
                                                                    <div className="flex flex-col lg:flex-row gap-6">
                                                                        <div className="w-full lg:w-1/2 flex flex-col">
                                                                            <h5 className="font-bold text-indigo-800 mb-2 flex items-center gap-1 text-sm">💡 AI 선정 이유</h5>
                                                                            <div className="bg-white p-4 rounded-xl border border-indigo-100 shadow-sm flex-1"><p className="text-sm text-gray-700 leading-relaxed">{clip.reason}</p></div>
                                                                        </div>
                                                                        <div className="w-full lg:w-1/2 flex flex-col">
                                                                            <h5 className="font-bold text-gray-700 mb-2 text-sm">📜 포함된 스크립트 내용 (클릭하여 이동)</h5>
                                                                            <div className="bg-white p-2 rounded-xl border border-gray-200 text-sm h-48 overflow-y-auto custom-scrollbar leading-relaxed">
                                                                                {playerData.transcripts ? (
                                                                                    playerData.transcripts.filter(t => clip.segments && clip.segments.some(seg => t.start >= seg.start && t.start < seg.end)).map((t, i) => {
                                                                                        const originalIndex = playerData.transcripts.indexOf(t);
                                                                                        const isActive = activeShortsId === uniqueKey && currentShortsOriginalTime >= t.start && currentShortsOriginalTime <= t.end;
                                                                                        return (
                                                                                            <div key={i} id={`shorts-script-item-${uniqueKey}-${originalIndex}`} onClick={(e) => handleJumpToShortsScript(e, videoElementId, t.start, clip.segments)} className={`p-2 rounded-lg cursor-pointer transition mb-1 flex gap-2 ${isActive ? 'bg-indigo-50 border border-indigo-200 text-indigo-900 shadow-sm scroll-mt-10' : 'hover:bg-gray-50 text-gray-600 border border-transparent'}`}>
                                                                                                <span className={`text-xs font-mono whitespace-nowrap mt-0.5 ${isActive ? 'text-indigo-600 font-bold' : 'text-indigo-300'}`}>{formatTimeSimple(t.start)}</span>
                                                                                                <p className={`${isActive ? 'font-medium' : ''}`}>{t.text}</p>
                                                                                            </div>
                                                                                        );
                                                                                    })
                                                                                ) : (<p className="text-gray-400 italic p-4">스크립트 정보를 불러올 수 없습니다.</p>)}
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            </details>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {activeTab === 'chapters' && (
                                    <div className="space-y-4 pb-10">
                                        {playerData.total_chapters > 0 ? (
                                            playerData.chapters.map((chap, idx) => {
                                                const isExpanded = expandedChapters[idx];
                                                return (
                                                    <div key={idx} className="group bg-white rounded-xl border border-gray-200 hover:border-indigo-300 transition overflow-hidden shadow-sm">
                                                        <div onClick={() => toggleChapter(idx)} className="p-4 flex gap-3 items-start cursor-pointer bg-white hover:bg-gray-50 transition select-none">
                                                            <button onClick={(e) => { e.stopPropagation(); seekVideo(chap.time.start); }} className="shrink-0 mt-0.5 px-2 py-1 bg-indigo-50 text-indigo-600 text-xs font-mono font-bold rounded hover:bg-indigo-600 hover:text-white transition flex items-center gap-1 z-10 border border-indigo-100">▶ {formatTimeSimple(chap.time.start)}</button>
                                                            <div className="flex-1">
                                                                <div className="flex justify-between items-center gap-4">
                                                                    <h3 className={`text-base font-bold transition leading-relaxed flex items-center gap-2 ${isExpanded ? 'text-indigo-700' : 'text-gray-700'}`}>
                                                                        {chap.type === 'Illustration' && <span className="text-[10px] bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded border border-yellow-200">✨ 예화</span>}
                                                                        {chap.type === 'Scripture' && <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded border border-blue-200">📖 성경</span>}
                                                                        {chap.type === 'Announcement' && <span className="text-[10px] bg-red-50 text-red-500 px-1.5 py-0.5 rounded border border-red-100">📢 광고</span>}
                                                                        {chap.type === 'Intro_Icebreak' && <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded border border-gray-200">🧊 인트로</span>}
                                                                        {chap.type === 'Application' && <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded border border-green-200">🎯 적용</span>}
                                                                        {chap.type === 'Prayer' && <span className="text-[10px] bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded border border-purple-200">🙏 기도</span>}
                                                                        {chap.title}
                                                                    </h3>
                                                                    <svg className={`w-5 h-5 text-gray-400 transform transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                                                                </div>
                                                                {!isExpanded && <p className="text-xs text-gray-400 mt-1 line-clamp-1">{chap.summary.replace(/\n/g, ' ')}</p>}
                                                            </div>
                                                        </div>
                                                        {isExpanded && <div className="px-4 pb-4 pl-[4.5rem] animate-fade-in border-t border-gray-50"><div className="text-gray-600 text-sm leading-7 mt-2">{chap.summary.split('\n').map((line, i) => (<p key={i} className="mb-1">{line}</p>))}</div></div>}
                                                    </div>
                                                );
                                            })
                                        ) : (
                                            <div className="text-center py-20 text-gray-400 bg-gray-50 rounded-xl border border-dashed border-gray-200 flex flex-col items-center gap-4">
                                                <p>아직 AI 분석이 진행되지 않았습니다.</p>
                                                <button onClick={(e) => handleStartAnalysis(e, playerData.video_filename, playerData.video_title)} className="px-4 py-2 bg-indigo-600 text-white rounded-lg font-bold hover:bg-indigo-700 transition">🤖 AI 챕터 분석 시작하기</button>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {activeTab === 'blog' && (
                                    <div className="max-w-3xl mx-auto pb-20 animate-fade-in px-4">
                                        {blogData ? (
                                            <div className="space-y-6">
                                                <div className="text-center mb-8 pt-4">
                                                    <h2 className="text-2xl md:text-3xl font-bold text-gray-900 mb-4 tracking-tight">{blogData.blog_title}</h2>
                                                    <div className="flex justify-center gap-2">
                                                        <button onClick={() => { const newStates = {}; blogData.chapters.forEach((_, i) => newStates[i] = true); setExpandedChapters(newStates); }} className="px-4 py-2 bg-white border border-gray-200 rounded-xl text-xs font-bold text-indigo-600 hover:bg-indigo-50 transition shadow-sm">📂 모두 펼치기</button>
                                                        <button onClick={() => setExpandedChapters({} )} className="px-4 py-2 bg-white border border-gray-200 rounded-xl text-xs font-bold text-gray-500 hover:bg-gray-100 transition shadow-sm">📁 모두 접기</button>
                                                        <button onClick={async () => { const fullText = blogData.chapters.map(c => `## ${c.title}\n\n${c.content}`).join("\n\n---\n\n"); try { await navigator.clipboard.writeText(fullText); alert('전체 마크다운이 복사되었습니다!'); } catch (e) { alert('복사 실패'); } }} className="px-4 py-2 bg-indigo-600 text-white rounded-xl text-xs font-bold hover:bg-indigo-700 transition shadow-md">📋 마크다운 복사</button>
                                                    </div>
                                                </div>
                                                <div className="space-y-4">
                                                    {blogData.chapters.map((chapter, idx) => {
                                                        const isExpanded = expandedChapters[idx];
                                                        return (
                                                            <div key={idx} className="bg-white border border-gray-200 rounded-2xl shadow-sm hover:border-indigo-300 transition-all overflow-hidden">
                                                                <div onClick={() => toggleChapter(idx)} className="p-5 flex items-center gap-4 cursor-pointer hover:bg-gray-50 transition select-none">
                                                                    <button onClick={(e) => { e.stopPropagation(); seekVideo(chapter.time.start); }} className="shrink-0 px-3 py-1.5 bg-indigo-50 text-indigo-600 text-[10px] font-mono font-bold rounded-lg hover:bg-indigo-600 hover:text-white transition border border-indigo-100 shadow-sm">▶ {formatTimeSimple(chapter.time.start)}</button>
                                                                    <h3 className={`flex-1 text-lg font-bold transition ${isExpanded ? 'text-indigo-700' : 'text-gray-800'}`}>{chapter.title}</h3>
                                                                    <svg className={`w-5 h-5 text-gray-400 transform transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                                                                </div>
                                                                {isExpanded && (
                                                                    <div className="px-6 pb-8 pt-2 border-t border-gray-50 animate-fade-in">
                                                                        <div className="markdown-body prose-custom text-[15px] leading-relaxed" dangerouslySetInnerHTML={{ __html: marked.parse(chapter.content)
                                                                            .replace(/(\(?|\[?)(\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2})(\)?|\]?)/g, (match, p1, timeStr, p2) => {
                                                                                const parts = timeStr.split(':');
                                                                                let totalSeconds = 0;
                                                                                if (parts.length === 3) {
                                                                                    totalSeconds = parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseInt(parts[2]);
                                                                                } else {
                                                                                    totalSeconds = parseInt(parts[0]) * 60 + parseInt(parts[1]);
                                                                                }
                                                                                // p1, p2는 괄호들을 유지하기 위함. 스타일과 이벤트를 포함한 span 반환
                                                                                return `<span class="timestamp-link" style="color: #4f46e5; text-decoration: underline; cursor: pointer; font-weight: bold;" onclick="if(window.seekFromTimestamp) window.seekFromTimestamp(${totalSeconds})">${p1}${timeStr}${p2}</span>`;
                                                                            })
                                                                        }}
                                                                        />
                                                                    </div>
                                                                )}
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="text-center py-24 bg-white rounded-3xl border-2 border-dashed border-gray-200 flex flex-col items-center gap-8 shadow-sm">
                                                <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center text-gray-300"><svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"></path></svg></div>
                                                <div className="space-y-2">
                                                    <p className="text-gray-500 font-bold">생성된 블로그 뷰 데이터가 없습니다.</p>
                                                    <button onClick={() => handleGenerateBlog(null, playerData.video_filename)} className="bg-indigo-600 text-white px-10 py-4 rounded-2xl font-bold hover:bg-indigo-700 transition shadow-xl">🚀 블로그 생성하기 (Step 3)</button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {activeTab === 'transcript' && (
                                    <div className="space-y-2 pb-10">
                                        {playerData.transcripts && playerData.transcripts.length > 0 ? (
                                            playerData.transcripts.map((line, idx) => (
                                                <div key={idx} ref={el => itemRefs.current[idx] = el} onClick={() => seekVideo(line.start)} className={`flex gap-4 p-4 rounded-xl transition cursor-pointer items-baseline border-l-4 ${activeIndex === idx ? 'bg-white border-indigo-500 shadow-md ring-1 ring-indigo-100 scroll-mt-24' : 'border-transparent hover:bg-white hover:shadow-sm text-gray-500'}`}>
                                                    <span className={`text-xs font-mono w-14 shrink-0 text-right ${activeIndex === idx ? 'text-indigo-600 font-bold' : 'text-gray-400'}`}>{formatTimeSimple(line.start)}</span>
                                                    <p className={`text-sm leading-relaxed flex-1 ${activeIndex === idx ? 'text-gray-900 font-bold' : ''}`}>{removePunctuation(line.text)}</p>
                                                </div>
                                            ))
                                        ) : (<div className="text-center py-20 text-gray-400 bg-gray-50 rounded-xl border border-dashed border-gray-200"><p>불러온 대본 데이터가 없습니다.</p></div>)}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);