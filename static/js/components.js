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

// [Sub Component] Task Monitor Widget (Upgraded v2)
window.TaskMonitor = function({ tasks, onCancel }) {
    if (!tasks || tasks.length === 0) return null;

    return (
        <div className="fixed bottom-6 right-6 w-96 bg-white rounded-xl shadow-2xl border border-indigo-100 overflow-hidden z-50 fade-in flex flex-col max-h-[80vh]">
            <div className="bg-indigo-600 px-4 py-3 flex justify-between items-center shrink-0">
                <h3 className="text-white font-bold text-sm flex items-center gap-2">
                    <span className="animate-spin h-3 w-3 border-2 border-white border-t-transparent rounded-full"></span>
                    작업 대기열 ({tasks.length})
                </h3>
                <span className="text-xs text-indigo-200">자동 갱신 중</span>
            </div>

            <div className="overflow-y-auto p-4 space-y-4 custom-scrollbar">
                {tasks.map((task, index) => {
                    let statusColor = "bg-indigo-500";
                    let statusText = `${task.progress}%`;
                    let isCancelable = true;

                    if (task.status === 'queued') {
                        statusColor = "bg-gray-300";
                        statusText = "대기 중";
                    } else if (task.status === 'canceling') {
                        statusColor = "bg-red-400";
                        statusText = "중단 중...";
                        isCancelable = false;
                    } else if (task.status === 'failed') {
                        statusColor = "bg-red-500";
                        statusText = "오류/취소";
                        isCancelable = false;
                    } else if (task.status === 'completed') {
                        statusColor = "bg-green-500";
                        statusText = "완료";
                        isCancelable = false;
                    }

                    return (
                        <div key={task.task_id} className="text-sm border-b border-gray-100 last:border-0 pb-3 last:pb-0 relative group">
                            <div className="flex justify-between text-gray-700 mb-1 items-center">
                                <div className="flex flex-col w-2/3">
                                    <span className="font-bold truncate" title={task.filename}>
                                        {index + 1}. {normalizeLegacyTitle(task.filename)}
                                    </span>
                                    <span className="text-xs text-gray-400">
                                        {task.type === 'clip_export' ? '✂️ 클립 생성' : 
                                         task.type === 'shorts_generation' ? '⚡ AI 숏츠 생성' :
                                         task.type === 'blog_generation' ? '📝 블로그 생성' :
                                         task.type === 'analysis' ? '🤖 AI 내용 분석' :
                                         task.type === 'transcription' ? '🎙️ 자막 생성' : '⚙️ 작업 중'}
                                    </span>
                                </div>
                                {isCancelable && (
                                    <button
                                        onClick={() => onCancel(task.task_id)}
                                        className="text-xs bg-white border border-red-200 text-red-500 px-2 py-0.5 rounded hover:bg-red-50 transition"
                                    >
                                        중단
                                    </button>
                                )}
                            </div>
                            <div className="w-full bg-gray-100 rounded-full h-2 mb-1.5 overflow-hidden">
                                {task.status === 'queued' ? (
                                    <div className="h-full w-full bg-[url('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAYAAACp8Z5+AAAAIklEQVQIW2NkQAKrVq36zwjjgzjwqgAA6gJwww==')] opacity-30"></div>
                                ) : (
                                    <div
                                        className={`h-2 rounded-full transition-all duration-500 ${statusColor}`}
                                        style={{ width: `${task.progress}%` }}>
                                    </div>
                                )}
                            </div>
                            <div className="flex justify-between items-center text-xs">
                                <p className="text-gray-500 truncate w-3/4">
                                    {task.status === 'queued' ? `대기 순번: ${index + 1}번째` : task.message}
                                </p>
                                <span className={`font-bold ${task.status === 'failed' ? 'text-red-500' : 'text-indigo-600'}`}>
                                    {statusText}
                                </span>
                            </div>
                            {task.status === 'completed' && task.type === 'clip_export' && task.result && (
                                <div className="mt-1 text-right">
                                    <a href={task.result.download_url} className="inline-block text-xs bg-green-500 text-white px-2 py-1 rounded hover:bg-green-600 transition font-bold no-underline" download>
                                        ⬇ 다운로드
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
    return (
        <div className="space-y-2">
            <div className="flex justify-between items-center">
                <label className="text-sm font-bold text-gray-700">{label}</label>
                <span className="text-[10px] text-indigo-500 font-mono font-bold bg-indigo-50 px-1.5 py-0.5 rounded uppercase tracking-wider">{task}</span>
            </div>
            <div className="relative">
                <input 
                    type="text" 
                    list={`list-${task}`}
                    className="w-full p-3 bg-gray-50 border border-gray-200 rounded-xl text-sm font-mono focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition text-gray-700"
                    placeholder="모델명을 입력하세요"
                    value={value || ""}
                    onChange={(e) => onChange(e.target.value)}
                />
                <datalist id={`list-${task}`}>
                    {suggestions && suggestions.map(opt => <option key={opt} value={opt} />)}
                </datalist>
            </div>
            <p className="text-[11px] text-gray-400 leading-relaxed pl-1">{description}</p>
        </div>
    );
};

// [Sub Component] Settings Modal
window.SettingsModal = function({ isOpen, onClose }) {
    const [settings, setSettings] = useState(null);
    const [isSaving, setIsSaving] = useState(false);

    const GEMINI_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-3-flash",
        "gemini-3-pro",
        "gemini-3-deep-think",
        "gemma-3-27b-it",
        "gemma-3-4b-it",
        "gemma-3-12b-it"
    ];

    const WHISPER_MODELS = [
        "mlx-community/whisper-large-v3-turbo-q4",
        "mlx-community/whisper-large-v3-mlx-4bit"
    ];

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
            setSettings(res.data);
        } catch (err) {
            console.error("Failed to fetch settings", err);
        }
    };

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await axios.post('/api/settings', settings);
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
                        description="영상의 오디오를 텍스트로 변환하는 Whisper 모델을 지정합니다. (MLX 최적화 모델 권장)"
                        value={settings.models['whisper']}
                        onChange={(val) => updateModel('whisper', val)}
                        suggestions={WHISPER_MODELS}
                    />
                    <TaskRow 
                        label="📝 메인 요약 & 챕터 분석" 
                        task="summarizer" 
                        description="전체 영상의 맥락을 파악하고 논리적인 챕터로 구분하는 핵심 작업에 사용됩니다."
                        value={settings.models['summarizer']}
                        onChange={(val) => updateModel('summarizer', val)}
                        suggestions={GEMINI_MODELS}
                    />
                    <TaskRow 
                        label="🏗️ 블로그 구조 기획" 
                        task="planner" 
                        description="전체 텍스트를 빠르게 스캔하여 블로그 포스트의 뼈대를 설계합니다. (경량 모델 권장)"
                        value={settings.models['planner']}
                        onChange={(val) => updateModel('planner', val)}
                        suggestions={GEMINI_MODELS}
                    />
                    <TaskRow 
                        label="✨ 문장 윤문 & 상세 작성" 
                        task="refiner" 
                        description="선택된 구간의 텍스트를 자연스러운 한국어 블로그 포스트로 변환합니다."
                        value={settings.models['refiner']}
                        onChange={(val) => updateModel('refiner', val)}
                        suggestions={GEMINI_MODELS}
                    />
                    <TaskRow 
                        label="🎬 숏츠 구간 발굴" 
                        task="shorts" 
                        description="임팩트 있는 구간을 찾고 구조화된 기획안을 생성합니다."
                        value={settings.models['shorts']}
                        onChange={(val) => updateModel('shorts', val)}
                        suggestions={GEMINI_MODELS}
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
