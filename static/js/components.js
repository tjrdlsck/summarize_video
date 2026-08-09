const { useState, useRef, useEffect, useMemo } = React;

// --- Utility Functions (Direct Global Assignment) ---

// 시간 포맷 유틸리티 (초 -> HH:MM:SS)
window.formatTime = (seconds) => {
    if (isNaN(seconds) || seconds < 0) return "00:00:00";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);

    const hStr = String(h).padStart(2, '0');
    const mStr = String(m).padStart(2, '0');
    const sStr = String(s).padStart(2, '0');

    return `${hStr}:${mStr}:${sStr}`;
};

// 정밀 시간 포맷 (초 -> HH:MM:SS.s)
window.formatTimeDetail = (seconds) => {
    if (isNaN(seconds) || seconds < 0) return "00:00:00.0";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    
    const hStr = String(h).padStart(2, '0');
    const mStr = String(m).padStart(2, '0');
    const sStr = s.toFixed(1).padStart(4, '0');
    
    return `${hStr}:${mStr}:${sStr}`;
};

window.removePunctuation = (text) => {
    if (!text) return "";
    return text.replace(/[.,?!]/g, "");
};

// [Add] 레거시 데이터(과거 분석 기록) 제목 정규화 유틸리티
window.normalizeLegacyTitle = (title) => {
    if (!title) return "제목 없음";
    let clean = title;
    clean = clean.replace(/^[0-9a-fA-F]{8}_/, "");
    clean = clean.replace(/\.[^/.]+$/, "");
    clean = clean.replace(/_/g, " ");
    return clean.trim();
};

// --- Components (Direct Global Assignment) ---

// [Sub Component] Task Monitor Widget (Upgraded v2 - Floating Glass Dock)
window.TaskMonitor = function({ tasks, onCancel }) {
    React.useEffect(() => {
        if (!tasks || tasks.length === 0) return;
        const autoDismissible = tasks.filter(t => 
            (t.status === 'failed' || t.status === 'canceled' || (t.status === 'completed' && t.type !== 'clip_export')) && t.finished_at
        );
        const timers = autoDismissible.map(t => {
            const elapsedMs = Date.now() - (t.finished_at * 1000);
            const remainingMs = Math.max(0, 10000 - elapsedMs);
            return setTimeout(() => {
                onCancel(t.task_id, true);
            }, remainingMs);
        });
        return () => timers.forEach(timer => clearTimeout(timer));
    }, [tasks, onCancel]);

    if (!tasks || tasks.length === 0) return null;

    const dismissibleTasks = tasks.filter(t => t.status === 'failed' || t.status === 'completed' || t.status === 'canceled');

    const handleCloseAll = () => {
        if (!confirm("모든 완료/취소된 내역을 지우시겠습니까?")) return;
        dismissibleTasks.forEach(t => onCancel(t.task_id, true));
    };

    return (
        <div className="fixed bottom-6 right-6 w-96 glass-panel rounded-2xl shadow-2xl border border-indigo-200/60 overflow-hidden z-50 animate-slide-in-right flex flex-col max-h-[80vh]">
            <div className="bg-slate-900/90 text-white px-4 py-3 flex justify-between items-center shrink-0 border-b border-slate-700/50">
                <h3 className="font-bold text-xs tracking-wide flex items-center gap-2 text-indigo-300">
                    <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                    </span>
                    AI 백그라운드 작업 대기열 ({tasks.length})
                </h3>
                {dismissibleTasks.length > 0 && (
                    <button 
                        onClick={handleCloseAll} 
                        className="text-[10px] font-bold bg-white/10 hover:bg-white/20 text-slate-300 px-2 py-1 rounded-lg transition"
                    >
                        모두 닫기
                    </button>
                )}
            </div>

            <div className="overflow-y-auto p-4 space-y-3 custom-scrollbar bg-slate-900/40 backdrop-blur-md">
                {tasks.map((task, index) => {
                    let statusColor = "bg-indigo-500";
                    let statusText = `${task.progress}%`;
                    let isCancelable = true;

                    if (task.status === 'queued') {
                        statusColor = "bg-slate-500";
                        statusText = "대기 중";
                    } else if (task.status === 'canceling') {
                        statusColor = "bg-amber-500";
                        statusText = "중단 중...";
                        isCancelable = false;
                    } else if (task.status === 'failed') {
                        statusColor = "bg-rose-500";
                        statusText = "오류/취소";
                        isCancelable = true;
                    } else if (task.status === 'completed') {
                        statusColor = "bg-emerald-500";
                        statusText = "완료";
                        isCancelable = true;
                    }

                    return (
                        <div key={task.task_id} className="text-xs bg-white/80 dark:bg-slate-800/80 p-3 rounded-xl border border-slate-200/50 dark:border-slate-700/50 shadow-sm relative transition hover:border-indigo-300">
                            <div className="flex justify-between items-start gap-2 mb-1.5">
                                <div className="flex flex-col min-w-0 flex-1">
                                    <span className="font-bold truncate text-slate-800 dark:text-slate-100" title={task.filename}>
                                        {index + 1}. {normalizeLegacyTitle(task.filename)}
                                    </span>
                                    <span className="text-[10px] text-slate-500 font-medium">
                                        {task.type === 'clip_export' ? '✂️ 클립 내보내기' : 
                                         task.type === 'shorts_generation' ? '⚡ AI 쇼츠 추출' :
                                         task.type === 'blog_generation' ? '📝 블로그 포스트 작성' :
                                         task.type === 'analysis' ? '🤖 AI 챕터 내용 분석' :
                                         task.type === 'transcription' ? '🎙️ 자막 Whisper 음성인식' : '⚙️ 백그라운드 처리'}
                                    </span>
                                </div>
                                {isCancelable && (
                                    <button
                                        onClick={() => {
                                            const isDismissible = task.status === 'failed' || task.status === 'completed' || task.status === 'canceled';
                                            onCancel(task.task_id, isDismissible);
                                        }}
                                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-lg border transition shrink-0 ${(task.status === 'failed' || task.status === 'completed' || task.status === 'canceled') ? 'border-slate-200 text-slate-500 hover:bg-slate-100' : 'border-rose-200 text-rose-600 hover:bg-rose-50'}`}
                                    >
                                        {(task.status === 'failed' || task.status === 'completed' || task.status === 'canceled') ? '닫기' : '중단'}
                                    </button>
                                )}
                            </div>
                            <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 mb-1.5 overflow-hidden">
                                {task.status === 'queued' ? (
                                    <div className="h-full w-full bg-slate-400 opacity-40 animate-pulse"></div>
                                ) : (
                                    <div
                                        className={`h-1.5 rounded-full transition-all duration-300 ${statusColor}`}
                                        style={{ width: `${task.progress}%` }}>
                                    </div>
                                )}
                            </div>
                            <div className="flex justify-between items-center text-[11px]">
                                <p className="text-slate-500 truncate max-w-[70%]">
                                    {task.status === 'queued' ? `대기 순번: ${index + 1}번째` : task.message}
                                </p>
                                <span className={`font-mono font-bold ${task.status === 'failed' ? 'text-rose-500' : 'text-indigo-600 dark:text-indigo-400'}`}>
                                    {statusText}
                                </span>
                            </div>
                            {task.status === 'completed' && task.type === 'clip_export' && task.result && (
                                <div className="mt-2 text-right border-t border-slate-100 pt-1.5">
                                    <a href={task.result.download_url} className="inline-flex items-center gap-1 text-[11px] bg-emerald-600 text-white px-2.5 py-1 rounded-lg hover:bg-emerald-700 transition font-bold no-underline shadow-sm" download>
                                        <span>⬇</span> 클립 다운로드
                                    </a>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// 구간 시각화 컴포넌트 (타임라인 바)
window.TimelineVisualizer = ({ totalDuration, start, end }) => {
    if (!totalDuration) return null;
    const startPct = Math.min(100, Math.max(0, (start / totalDuration) * 100));
    const endPct = Math.min(100, Math.max(0, (end / totalDuration) * 100));
    const widthPct = endPct - startPct;

    return (
        <div className="w-full mt-3 mb-1 px-1">
            <div className="flex justify-between text-xs text-gray-400 mb-1 font-mono">
                <span>0:00</span>
                <span>{formatTimeDetail(totalDuration).split('.')[0]}</span>
            </div>
            <div className="relative w-full h-4 bg-gray-200 rounded-full overflow-hidden shadow-inner">
                <div
                    className="absolute top-0 h-full bg-indigo-500 opacity-80 transition-all duration-300 ease-out"
                    style={{ left: `${startPct}%`, width: `${widthPct}%` }}
                ></div>
            </div>
            <div className="text-center mt-1">
                <span className="text-xs font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
                    선택 구간: {((end - start) || 0).toFixed(1)}초
                </span>
            </div>
        </div>
    );
};

// [Sub Component] Segmented Control (Slide Tab)
window.SegmentedControl = function({ activeTab, onChange }) {
    return (
        <div className="bg-gray-100 p-1 rounded-xl flex relative w-48 h-10 shadow-inner">
            {/* Sliding Background */}
            <div 
                className="absolute top-1 bottom-1 bg-white rounded-lg shadow-sm transition-all duration-300 ease-out z-0"
                style={{ 
                    width: 'calc(50% - 4px)',
                    left: activeTab === 'analysis' ? '4px' : '50%'
                }}
            ></div>
            
            <button 
                onClick={() => onChange('analysis')}
                className={`flex-1 text-sm font-bold z-10 transition-colors duration-200 ${activeTab === 'analysis' ? 'text-indigo-600' : 'text-gray-400 hover:text-gray-600'}`}
            >
                분석
            </button>
            <button 
                onClick={() => onChange('subtitle')}
                className={`flex-1 text-sm font-bold z-10 transition-colors duration-200 ${activeTab === 'subtitle' ? 'text-indigo-600' : 'text-gray-400 hover:text-gray-600'}`}
            >
                자막
            </button>
        </div>
    );
};

// --- [Helper Component] TaskRow (Moved Outside to Prevent Focus Loss) ---
const TaskRow = ({ label, task, description, value, onChange, suggestions }) => {
    // value가 suggestions에 없는 경우 목록에 추가 (수동 입력된 기존 값 보존)
    const options = suggestions ? [...suggestions] : [];
    if (value && !options.includes(value)) {
        options.unshift(value);
    }

    return (
        <div className="space-y-2">
            <div className="flex justify-between items-center">
                <label className="text-sm font-bold text-gray-700">{label}</label>
                <span className="text-[10px] text-indigo-500 font-mono font-bold bg-indigo-50 px-1.5 py-0.5 rounded uppercase tracking-wider">{task}</span>
            </div>
            <div className="relative">
                <select 
                    className="w-full p-3 bg-gray-50 border border-gray-200 rounded-xl text-sm font-mono focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition text-gray-700 appearance-none cursor-pointer"
                    value={value || ""}
                    onChange={(e) => onChange(e.target.value)}
                >
                    <option value="" disabled>모델을 선택하세요</option>
                    {options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-gray-500">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                </div>
            </div>
            <p className="text-[11px] text-gray-400 leading-relaxed pl-1">{description}</p>
        </div>
    );
};

// [Sub Component] Settings Modal
window.SettingsModal = function({ isOpen, onClose }) {
    const [settings, setSettings] = useState(null);
    const [isSaving, setIsSaving] = useState(false);

    const [platform, setPlatform] = useState("linux");
    const [whisperModels, setWhisperModels] = useState([]);
    const [geminiModels, setGeminiModels] = useState([]);

    useEffect(() => {
        if (isOpen) fetchSettings();
    }, [isOpen]);

    // [New] ESC Key Listener
    useEffect(() => {
        const handleEsc = (e) => {
            if (isOpen && e.key === 'Escape') onClose();
        };
        window.addEventListener('keydown', handleEsc);
        return () => window.removeEventListener('keydown', handleEsc);
    }, [isOpen, onClose]);

    const fetchSettings = async () => {
        try {
            const res = await axios.get('/api/settings');
            setSettings({ 
                models: res.data.models || {},
                whisper_gpu_tier: res.data.whisper_gpu_tier || "low"
            });
            setPlatform(res.data.platform || "linux");
            setWhisperModels(res.data.whisper_models || []);
            setGeminiModels(res.data.gemini_models || []);
        } catch (err) {
            console.error("Failed to fetch settings", err);
        }
    };

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await axios.post('/api/settings', { 
                models: settings.models,
                whisper_gpu_tier: settings.whisper_gpu_tier
            });
            alert("설정이 저장되었습니다. 즉시 적용됩니다.");
            onClose();
        } catch (err) {
            alert("저장 실패: " + err.message);
        } finally {
            setIsSaving(false);
        }
    };

    const updateModel = (task, model) => {
        setSettings(prev => ({
            ...prev,
            models: { ...prev.models, [task]: model }
        }));
    };

    if (!isOpen || !settings) return null;

    return (
        <div 
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
            onClick={onClose}
        >
            <div 
                className="bg-white rounded-3xl shadow-2xl w-full max-w-lg overflow-hidden animate-scale-in border border-white/20"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="bg-indigo-600 p-6 text-white relative">
                    <div className="flex items-center gap-3">
                        <div className="bg-white/20 p-2 rounded-2xl">
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                        </div>
                        <div>
                            <h2 className="text-xl font-bold">시스템 모델 설정</h2>
                            <p className="text-indigo-100 text-xs font-medium">개별 기능에 최적화된 엔진을 지정하세요.</p>
                        </div>
                    </div>
                    <button onClick={onClose} className="absolute top-6 right-6 text-white/60 hover:text-white transition">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    </button>
                </div>

                {/* Content */}
                <div className="p-8 max-h-[65vh] overflow-y-auto custom-scrollbar space-y-8 bg-white">
                    <TaskRow 
                        label="🎙️ 음성 인식 (STT)" 
                        task="whisper" 
                        description={`영상의 오디오를 텍스트로 변환하는 Whisper 모델을 지정합니다. ${platform === 'darwin' ? '(MLX 최적화 모델 권장)' : '(Faster-Whisper 가속 모델 권장)'}`}
                        value={settings.models['whisper']}
                        onChange={(val) => updateModel('whisper', val)}
                        suggestions={whisperModels}
                    />

                    <div className="space-y-2">
                        <div className="flex justify-between items-center">
                            <label className="text-sm font-bold text-gray-700">🚀 GPU 가속 수준 (Whisper Batch Size)</label>
                            <span className="text-[10px] text-indigo-500 font-mono font-bold bg-indigo-50 px-1.5 py-0.5 rounded uppercase tracking-wider">gpu_tier</span>
                        </div>
                        <div className="relative">
                            <select 
                                className="w-full p-3 bg-gray-50 border border-gray-200 rounded-xl text-sm font-mono focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition text-gray-700 appearance-none cursor-pointer disabled:bg-gray-100 disabled:text-gray-400" 
                                value={settings.whisper_gpu_tier || "low"} 
                                onChange={(e) => setSettings(prev => ({ ...prev, whisper_gpu_tier: e.target.value }))}
                                disabled={platform === 'darwin'}
                            >
                                <option value="mac">Apple Silicon (MacBook) - 💡 자동 최적화 적용</option>
                                <option value="low">일반 PC (VRAM 8GB 이하) - 💡 안정성 위주 (기본값)</option>
                                <option value="mid">고성능 PC (VRAM 12GB~16GB) - 💡 빠른 속도</option>
                                <option value="high">워크스테이션 (VRAM 24GB 이상) - 💡 최고 속도 (OOM 주의)</option>
                            </select>
                            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-gray-500">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                            </div>
                        </div>
                        <p className="text-[11px] text-gray-400 leading-relaxed pl-1">
                            {platform === 'darwin' 
                                ? "맥 환경(MLX)에서는 구조상 통합 메모리를 스스로 제어하므로 별도 선택이 불필요합니다." 
                                : "GPU VRAM 용량에 맞춰 Whisper 추론 속도를 극대화합니다. OOM 발생 시 단계를 낮추세요."}
                        </p>
                    </div>

                    <TaskRow 
                        label="📝 메인 요약 & 챕터 분석" 
                        task="summarizer" 
                        description="전체 영상의 맥락을 파악하고 논리적인 챕터로 구분하는 핵심 작업에 사용됩니다."
                        value={settings.models['summarizer']}
                        onChange={(val) => updateModel('summarizer', val)}
                        suggestions={geminiModels}
                    />
                    <TaskRow 
                        label="🏗️ 블로그 구조 기획" 
                        task="planner" 
                        description="전체 텍스트를 빠르게 스캔하여 블로그 포스트의 뼈대를 설계합니다. (경량 모델 권장)"
                        value={settings.models['planner']}
                        onChange={(val) => updateModel('planner', val)}
                        suggestions={geminiModels}
                    />
                    <TaskRow 
                        label="✨ 문장 윤문 & 상세 작성" 
                        task="refiner" 
                        description="선택된 구간의 텍스트를 자연스러운 한국어 블로그 포스트로 변환합니다."
                        value={settings.models['refiner']}
                        onChange={(val) => updateModel('refiner', val)}
                        suggestions={geminiModels}
                    />
                    <TaskRow 
                        label="🎬 숏츠 구간 발굴" 
                        task="shorts" 
                        description="임팩트 있는 구간을 찾고 구조화된 기획안을 생성합니다."
                        value={settings.models['shorts']}
                        onChange={(val) => updateModel('shorts', val)}
                        suggestions={geminiModels}
                    />

                    <div className="bg-gray-50 p-4 rounded-2xl border border-dashed border-gray-200">
                        <div className="flex items-center gap-2 mb-1 text-indigo-600">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-1.622 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path></svg>
                            <span className="text-xs font-bold uppercase tracking-wider">개인화 설정 보호됨</span>
                        </div>
                        <p className="text-[11px] text-gray-500 leading-relaxed">이 설정은 <code className="bg-white px-1 py-0.5 rounded border text-indigo-500">data/config.json</code>에 안전하게 저장되며, Git 업데이트 시에도 초기화되지 않고 유지됩니다.</p>
                    </div>
                </div>

                {/* Footer */}
                <div className="p-6 bg-gray-50 border-t flex gap-3">
                    <button 
                        onClick={onClose}
                        className="flex-1 py-3 text-sm font-bold text-gray-500 bg-white border border-gray-200 rounded-2xl hover:bg-gray-100 transition shadow-sm"
                    >
                        닫기
                    </button>
                    <button 
                        onClick={handleSave}
                        disabled={isSaving}
                        className="flex-[2] py-3 text-sm font-bold text-white bg-indigo-600 rounded-2xl hover:bg-indigo-700 transition shadow-lg shadow-indigo-200 flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                        {isSaving ? (
                            <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
                        ) : '💾 설정 저장 및 즉시 적용'}
                    </button>
                </div>
            </div>
        </div>
    );
};

// [New Component] Video Upload & Batch Analysis Modal
window.VideoUploadModal = function({ isOpen, onClose, onSubmit, uploadProgress, uploadStatusText, isUploading }) {
    const [tab, setTab] = useState('url'); // 'url' or 'file'
    const [urlInput, setUrlInput] = useState("");
    const [fileInput, setFileInput] = useState(null);
    const [titleInput, setTitleInput] = useState("");
    const [contentType, setContentType] = useState("streaming");
    
    // 분석 옵션
    const [runSummary, setRunSummary] = useState(true);
    const [runBlog, setRunBlog] = useState(false);

    useEffect(() => {
        if (runBlog) {
            setRunSummary(true); // 블로그 체크 시 요약도 강제 체크
        }
    }, [runBlog]);

    // 사용자 정의 설정 (Advanced Settings)
    const [showAdvancedSettings, setShowAdvancedSettings] = useState(false);
    const [whisperLang, setWhisperLang] = useState("ko");
    const [whisperPrompt, setWhisperPrompt] = useState("");
    const [whisperCondition, setWhisperCondition] = useState(false);
    const [whisperTemp, setWhisperTemp] = useState(0.0);
    const [whisperVad, setWhisperVad] = useState(true);

    if (!isOpen) return null;

    const handleSubmit = () => {
        if (tab === 'url' && !urlInput.trim()) return alert("URL을 입력해주세요.");
        if (tab === 'file' && !fileInput) return alert("업로드할 파일을 선택해주세요.");
        
        onSubmit({
            sourceType: tab,
            url: urlInput,
            file: fileInput,
            title: titleInput,
            contentType,
            runSummary,
            runBlog,
            whisperLang,
            whisperPrompt,
            whisperCondition,
            whisperTemp,
            whisperVad
        });
    };

    return (
        <div 
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
        >
            <div 
                className="bg-white rounded-3xl shadow-2xl w-full max-w-lg overflow-hidden animate-scale-in border border-white/20 flex flex-col max-h-[90vh]"
            >
                {/* Header */}
                <div className="bg-indigo-600 p-6 text-white relative shrink-0">
                    <div className="flex items-center gap-3">
                        <div className="bg-white/20 p-2 rounded-2xl">
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                        </div>
                        <div>
                            <h2 className="text-xl font-bold">새 영상 등록 및 AI 분석 설정</h2>
                            <p className="text-indigo-100 text-xs font-medium">영상을 추가하고 일괄 분석 작업을 구성하세요.</p>
                        </div>
                    </div>
                    {!isUploading && (
                        <button onClick={onClose} className="absolute top-6 right-6 text-white/60 hover:text-white transition">
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                    )}
                </div>

                {/* Content */}
                <div className="p-6 overflow-y-auto custom-scrollbar bg-white space-y-6">
                    {/* Tab Selection */}
                    <div className="flex bg-gray-100 p-1 rounded-xl w-full relative">
                        <div 
                            className="absolute top-1 bottom-1 bg-white rounded-lg shadow-sm transition-all duration-300 ease-out z-0"
                            style={{ 
                                width: 'calc(50% - 4px)',
                                left: tab === 'url' ? '4px' : 'calc(50%)'
                            }}
                        ></div>
                        <button onClick={() => !isUploading && setTab('url')} className={`flex-1 py-2 text-sm font-bold z-10 transition ${tab === 'url' ? 'text-indigo-600' : 'text-gray-400'}`}>YouTube URL</button>
                        <button onClick={() => !isUploading && setTab('file')} className={`flex-1 py-2 text-sm font-bold z-10 transition ${tab === 'file' ? 'text-indigo-600' : 'text-gray-400'}`}>로컬 파일 업로드</button>
                    </div>

                    {/* Source Input */}
                    <div className="space-y-4">
                        {tab === 'url' ? (
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">YouTube URL</label>
                                <input type="text" placeholder="https://youtube.com/..." className="w-full p-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none text-sm" value={urlInput} onChange={(e) => setUrlInput(e.target.value)} disabled={isUploading} />
                            </div>
                        ) : (
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">로컬 MP4 파일</label>
                                <label className="block w-full cursor-pointer bg-gray-50 border-2 border-dashed border-gray-300 rounded-xl p-4 text-center hover:bg-indigo-50 transition relative overflow-hidden">
                                    <span className="relative z-10 font-medium text-gray-500">
                                        {fileInput ? fileInput.name : "📁 여기를 클릭하여 파일 선택"}
                                    </span>
                                    {isUploading && uploadProgress > 0 && uploadProgress < 100 && (
                                        <div className="absolute top-0 left-0 h-full bg-blue-100 z-0 transition-all duration-300" style={{ width: `${uploadProgress}%`, opacity: 0.5 }}></div>
                                    )}
                                    <input type="file" accept="video/mp4" className="hidden" onChange={(e) => setFileInput(e.target.files[0])} disabled={isUploading} />
                                </label>
                                {isUploading && uploadProgress > 0 && <p className="text-xs text-indigo-600 text-center mt-2 font-bold animate-pulse">업로드 진행 중... {uploadProgress}%</p>}
                            </div>
                        )}

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs font-bold text-gray-500 mb-1">콘텐츠 타입</label>
                                <select className="w-full p-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none text-sm bg-white" value={contentType} onChange={(e) => setContentType(e.target.value)} disabled={isUploading}>
                                    <option value="streaming">스트리밍(티키타카)</option>
                                    <option value="sermon">설교</option>
                                    <option value="informational">정보형</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs font-bold text-gray-500 mb-1">영상 제목 (선택)</label>
                                <input type="text" placeholder="자동 생성" className="w-full p-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none text-sm" value={titleInput} onChange={(e) => setTitleInput(e.target.value)} disabled={isUploading} />
                            </div>
                        </div>
                    </div>

                    <hr className="border-gray-100" />

                    {/* Options */}
                    <div className="space-y-3">
                        <h3 className="text-sm font-bold text-gray-700">분석 옵션 선택</h3>
                        
                        <label className="flex items-center gap-3 p-3 rounded-xl border border-gray-200 bg-gray-50 opacity-80 cursor-not-allowed">
                            <input type="checkbox" checked readOnly className="w-5 h-5 text-indigo-600 rounded" />
                            <div>
                                <div className="font-bold text-sm">🎙️ 위스퍼 자막 추출 (STT)</div>
                                <div className="text-xs text-gray-500">기본 필수 작업 (음성을 텍스트로 변환합니다)</div>
                            </div>
                        </label>
                        
                        <label className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition ${runSummary ? 'border-indigo-400 bg-indigo-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                            <input type="checkbox" checked={runSummary} onChange={(e) => setRunSummary(e.target.checked)} disabled={runBlog || isUploading} className="w-5 h-5 text-indigo-600 rounded" />
                            <div>
                                <div className="font-bold text-sm">🤖 AI 챕터 요약 분석</div>
                                <div className="text-xs text-gray-500">전체 맥락을 파악하고 논리적 챕터로 구분합니다</div>
                            </div>
                        </label>
                        
                        <label className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition ${runBlog ? 'border-purple-400 bg-purple-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                            <input type="checkbox" checked={runBlog} onChange={(e) => setRunBlog(e.target.checked)} disabled={isUploading} className="w-5 h-5 text-purple-600 rounded" />
                            <div>
                                <div className="font-bold text-sm">📝 AI 블로그 포스트 초안 작성</div>
                                <div className="text-xs text-gray-500">요약 결과를 바탕으로 세부 블로그 글을 작성합니다</div>
                            </div>
                        </label>
                    </div>

                    <hr className="border-gray-100" />

                    {/* Advanced Settings Toggle */}
                    <div>
                        <button 
                            onClick={() => setShowAdvancedSettings(!showAdvancedSettings)}
                            className="flex items-center gap-2 text-sm font-bold text-gray-700 hover:text-indigo-600 transition"
                        >
                            ⚙️ 사용자 정의 (Advanced Settings)
                            <svg className={`w-4 h-4 transition-transform duration-300 ${showAdvancedSettings ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                        </button>
                        
                        {showAdvancedSettings && (
                            <div className="mt-4 space-y-4 p-4 bg-gray-50 border border-gray-200 rounded-xl animate-fade-in text-sm">
                                <div>
                                    <label className="block text-xs font-bold text-gray-500 mb-1">오디오 언어 (Language)</label>
                                    <select className="w-full p-2 border border-gray-300 rounded outline-none bg-white" value={whisperLang} onChange={(e) => setWhisperLang(e.target.value)}>
                                        <option value="ko">한국어 (Korean)</option>
                                        <option value="auto">자동 감지 (Auto)</option>
                                        <option value="en">영어 (English)</option>
                                        <option value="ja">일본어 (Japanese)</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs font-bold text-gray-500 mb-1">고유명사/전문용어 사전 (Initial Prompt)</label>
                                    <input type="text" placeholder="예: MLX, Faster-Whisper, FastAPI" className="w-full p-2 border border-gray-300 rounded outline-none" value={whisperPrompt} onChange={(e) => setWhisperPrompt(e.target.value)} />
                                    <p className="text-[10px] text-gray-400 mt-1">비워두면 콘텐츠 타입에 따른 기본값이 적용됩니다.</p>
                                </div>
                                <div>
                                    <label className="block text-xs font-bold text-gray-500 mb-1">창의성 / 정확도 조절 (Temperature: {whisperTemp.toFixed(1)})</label>
                                    <input type="range" min="0" max="1" step="0.1" className="w-full" value={whisperTemp} onChange={(e) => setWhisperTemp(parseFloat(e.target.value))} />
                                    <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                                        <span>0.0 (정확도 우선)</span>
                                        <span>1.0 (유연함 우선)</span>
                                    </div>
                                </div>
                                <div className="grid grid-cols-2 gap-4">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" className="w-4 h-4 text-indigo-600 rounded" checked={whisperCondition} onChange={(e) => setWhisperCondition(e.target.checked)} />
                                        <span className="text-xs font-bold text-gray-700">이전 문맥 참조</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" className="w-4 h-4 text-indigo-600 rounded" checked={whisperVad} onChange={(e) => setWhisperVad(e.target.checked)} />
                                        <span className="text-xs font-bold text-gray-700">묵음 필터링 (VAD)</span>
                                    </label>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Footer */}
                <div className="p-6 bg-gray-50 border-t shrink-0 flex gap-3">
                    <button 
                        onClick={onClose}
                        className="flex-1 py-3 text-sm font-bold text-gray-500 bg-white border border-gray-200 rounded-2xl hover:bg-gray-100 transition shadow-sm"
                    >
                        취소
                    </button>
                    <button 
                        onClick={handleSubmit}
                        disabled={isUploading || (tab === 'file' && !fileInput)}
                        className="flex-[2] py-3 text-sm font-bold text-white bg-indigo-600 rounded-2xl hover:bg-indigo-700 transition shadow-lg shadow-indigo-200 disabled:opacity-50 flex items-center justify-center gap-2"
                    >
                        {isUploading ? (
                            <><span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span> {uploadStatusText || '등록 중...'}</>
                        ) : '🚀 분석 시작'}
                    </button>
                </div>
            </div>
        </div>
    );
};

// [New Component] Regenerate Modal
window.RegenerateModal = function({ isOpen, onClose, onSubmit, initialContentType, hasChapters }) {
    const [contentType, setContentType] = useState(initialContentType || "streaming");
    const [runTranscription, setRunTranscription] = useState(false);
    const [runSummary, setRunSummary] = useState(true);
    const [runBlog, setRunBlog] = useState(false);

    // Whisper Advanced Settings
    const [whisperLang, setWhisperLang] = useState("ko");
    const [whisperPrompt, setWhisperPrompt] = useState("");
    const [whisperCondition, setWhisperCondition] = useState(false);
    const [whisperTemp, setWhisperTemp] = useState(0.0);
    const [whisperVad, setWhisperVad] = useState(true);

    useEffect(() => {
        if (isOpen) {
            setContentType(initialContentType || "streaming");
            setRunTranscription(false);
            setRunSummary(true);
            setRunBlog(false);
            setWhisperLang("ko");
            setWhisperPrompt("");
            setWhisperCondition(false);
            setWhisperTemp(0.0);
            setWhisperVad(true);
        }
    }, [isOpen, initialContentType]);

    useEffect(() => {
        if (runBlog) {
            setRunSummary(true);
        }
    }, [runBlog]);

    const isBlogDisabled = !runSummary;
    const isSummaryDisabled = runBlog; // 블로그 작성 시 요약 필수

    if (!isOpen) return null;

    const handleSubmit = () => {
        onSubmit({
            contentType,
            runTranscription,
            runSummary,
            runBlog,
            whisperLang,
            whisperPrompt,
            whisperCondition,
            whisperTemp,
            whisperVad
        });
    };

    return (
        <div 
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
            onClick={onClose}
        >
            <div 
                className="bg-white rounded-3xl shadow-2xl w-full max-w-sm overflow-hidden animate-scale-in border border-white/20 flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="bg-indigo-600 p-5 text-white flex justify-between items-center shrink-0">
                    <h2 className="text-lg font-bold">🔄 AI 콘텐츠 재생성</h2>
                    <button onClick={onClose} className="text-white/60 hover:text-white transition">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    </button>
                </div>

                <div className="p-6 space-y-5 bg-white">
                    <div>
                        <label className="block text-xs font-bold text-gray-500 mb-2">콘텐츠 타입 재설정</label>
                        <select 
                            className="w-full p-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none text-sm bg-white" 
                            value={contentType} 
                            onChange={(e) => setContentType(e.target.value)}
                        >
                            <option value="streaming">스트리밍(티키타카)</option>
                            <option value="sermon">설교</option>
                            <option value="informational">정보형</option>
                        </select>
                    </div>

                    <div className="space-y-3">
                        <label className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition ${runTranscription ? 'border-indigo-400 bg-indigo-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                            <input type="checkbox" checked={runTranscription} onChange={(e) => setRunTranscription(e.target.checked)} className="w-5 h-5 text-indigo-600 rounded" />
                            <div>
                                <div className="font-bold text-sm">🎙️ 자막 AI 재추출 (Whisper)</div>
                            </div>
                        </label>

                        {runTranscription && (
                            <div className="p-4 bg-gray-50 rounded-xl space-y-4 border border-indigo-100 text-left animate-fade-in mt-2 mb-4">
                                <div className="flex justify-between items-center mb-2 border-b pb-2 border-gray-200">
                                    <span className="text-xs font-bold text-indigo-600 uppercase tracking-wide flex items-center gap-1">
                                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"></path></svg>
                                        Whisper 사용자 정의 설정
                                    </span>
                                </div>
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-xs font-bold text-gray-500 mb-1">언어 강제 지정</label>
                                        <select className="w-full p-2 border border-gray-300 rounded outline-none bg-white" value={whisperLang} onChange={(e) => setWhisperLang(e.target.value)}>
                                            <option value="auto">자동 감지 (Auto)</option>
                                            <option value="ko">한국어 (Korean)</option>
                                            <option value="en">영어 (English)</option>
                                            <option value="ja">일본어 (Japanese)</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-bold text-gray-500 mb-1">창의성 (Temperature)</label>
                                        <div className="flex items-center gap-2">
                                            <input type="range" min="0" max="1" step="0.1" value={whisperTemp} onChange={(e) => setWhisperTemp(parseFloat(e.target.value))} className="w-full accent-indigo-600" />
                                            <span className="text-xs font-mono w-6">{whisperTemp}</span>
                                        </div>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs font-bold text-gray-500 mb-1">고유명사 프롬프트 (Initial Prompt)</label>
                                    <input type="text" placeholder="예: 썸머라이즈비디오, 애플리케이션, AI..." className="w-full p-2 border border-gray-300 rounded outline-none text-xs bg-white" value={whisperPrompt} onChange={(e) => setWhisperPrompt(e.target.value)} />
                                </div>
                                <div className="grid grid-cols-2 gap-4">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" className="w-4 h-4 text-indigo-600 rounded" checked={whisperCondition} onChange={(e) => setWhisperCondition(e.target.checked)} />
                                        <span className="text-xs font-bold text-gray-700">이전 문맥 참조</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input type="checkbox" className="w-4 h-4 text-indigo-600 rounded" checked={whisperVad} onChange={(e) => setWhisperVad(e.target.checked)} />
                                        <span className="text-xs font-bold text-gray-700">묵음 필터링 (VAD)</span>
                                    </label>
                                </div>
                            </div>
                        )}

                        <label className={`flex items-center gap-3 p-3 rounded-xl border transition ${runSummary ? 'border-indigo-400 bg-indigo-50' : 'border-gray-200 hover:bg-gray-50'} ${isSummaryDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                            <input type="checkbox" checked={runSummary} onChange={(e) => setRunSummary(e.target.checked)} disabled={isSummaryDisabled} className="w-5 h-5 text-indigo-600 rounded" />
                            <div>
                                <div className="font-bold text-sm">🤖 AI 챕터 요약 재작성</div>
                            </div>
                        </label>
                        
                        <label className={`flex items-center gap-3 p-3 rounded-xl border transition ${runBlog ? 'border-purple-400 bg-purple-50' : 'border-gray-200 hover:bg-gray-50'} ${isBlogDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                            <input type="checkbox" checked={runBlog} onChange={(e) => setRunBlog(e.target.checked)} disabled={isBlogDisabled} className="w-5 h-5 text-purple-600 rounded" />
                            <div>
                                <div className="font-bold text-sm">📝 블로그 포스트 재작성</div>
                            </div>
                        </label>
                    </div>
                </div>

                <div className="p-5 bg-gray-50 border-t shrink-0 flex gap-3">
                    <button onClick={onClose} className="flex-1 py-2.5 text-sm font-bold text-gray-500 bg-white border border-gray-200 rounded-xl hover:bg-gray-100 transition shadow-sm">
                        취소
                    </button>
                    <button onClick={handleSubmit} className="flex-[2] py-2.5 text-sm font-bold text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 transition shadow-md flex items-center justify-center gap-2">
                        ✨ 재생성 시작
                    </button>
                </div>
            </div>
        </div>
    );
};

// --- [New] Log Viewer Modal ---
function LogViewerModal({ isOpen, onClose }) {
    const [logs, setLogs] = React.useState([]);
    const [selectedLogContent, setSelectedLogContent] = React.useState("");
    const [loadingLogs, setLoadingLogs] = React.useState(false);
    const [loadingContent, setLoadingContent] = React.useState(false);

    React.useEffect(() => {
        if (isOpen) {
            fetchLogs();
            setSelectedLogContent("");
        }
    }, [isOpen]);

    const fetchLogs = async () => {
        setLoadingLogs(true);
        try {
            const res = await axios.get('/api/system/logs');
            setLogs(res.data.logs || []);
        } catch (error) {
            console.error("Failed to fetch logs", error);
            alert("로그 목록을 불러오지 못했습니다.");
        } finally {
            setLoadingLogs(false);
        }
    };

    const loadLogContent = async (filename) => {
        setLoadingContent(true);
        try {
            const res = await axios.get(`/api/system/logs/${filename}`);
            setSelectedLogContent(res.data);
        } catch (error) {
            console.error("Failed to fetch log content", error);
            setSelectedLogContent("로그 내용을 불러오지 못했습니다.");
        } finally {
            setLoadingContent(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-3xl w-full max-w-6xl h-[85vh] shadow-2xl flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200">
                
                {/* Header */}
                <div className="flex justify-between items-center p-6 border-b shrink-0 bg-gray-50">
                    <div>
                        <h2 className="text-2xl font-bold text-gray-800">서버 오류 로그 뷰어</h2>
                        <p className="text-sm text-gray-500 mt-1">시스템에서 발생한 예외 및 에러 내역을 확인합니다.</p>
                    </div>
                    <div className="flex gap-3">
                        <button onClick={fetchLogs} className="p-2 text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-full transition" title="새로고침">
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                        </button>
                        <button onClick={onClose} className="p-2 text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-full transition">
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                    </div>
                </div>

                {/* Content Body */}
                <div className="flex flex-1 overflow-hidden">
                    {/* Left: Log File List */}
                    <div className="w-1/3 border-r bg-white flex flex-col overflow-hidden">
                        <div className="p-4 border-b bg-gray-50 font-bold text-gray-700">로그 파일 목록</div>
                        <div className="flex-1 overflow-y-auto p-2 space-y-1">
                            {loadingLogs ? (
                                <div className="text-center py-10 text-gray-400">목록 불러오는 중...</div>
                            ) : logs.length === 0 ? (
                                <div className="text-center py-10 text-gray-400">로그 파일이 없습니다.</div>
                            ) : (
                                logs.map(log => (
                                    <button 
                                        key={log.filename}
                                        onClick={() => loadLogContent(log.filename)}
                                        className="w-full text-left p-3 rounded-xl hover:bg-gray-100 transition border border-transparent focus:outline-none"
                                    >
                                        <div className="font-bold text-gray-800 text-sm truncate">{log.filename}</div>
                                        <div className="flex justify-between mt-1 text-xs text-gray-400">
                                            <span>{new Date(log.modified).toLocaleString()}</span>
                                            <span>{(log.size / 1024).toFixed(1)} KB</span>
                                        </div>
                                    </button>
                                ))
                            )}
                        </div>
                    </div>

                    {/* Right: Log Content */}
                    <div className="flex-1 bg-gray-900 flex flex-col overflow-hidden relative">
                        {loadingContent ? (
                            <div className="flex-1 flex items-center justify-center text-gray-400">내용 불러오는 중...</div>
                        ) : selectedLogContent ? (
                            <pre className="flex-1 overflow-auto p-6 text-sm font-mono text-green-400 whitespace-pre-wrap">
                                {selectedLogContent}
                            </pre>
                        ) : (
                            <div className="flex-1 flex items-center justify-center text-gray-500">
                                좌측에서 로그 파일을 선택해주세요.
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
