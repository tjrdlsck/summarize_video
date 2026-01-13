const { useState, useRef, useEffect, useMemo } = React;

// 시간 포맷 유틸리티 (초 -> HH:MM:SS)
const formatTime = (seconds) => {
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
const formatTimeDetail = (seconds) => {
    if (isNaN(seconds) || seconds < 0) return "00:00:00.0";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    
    const hStr = String(h).padStart(2, '0');
    const mStr = String(m).padStart(2, '0');
    const sStr = s.toFixed(1).padStart(4, '0');
    
    return `${hStr}:${mStr}:${sStr}`;
};

const removePunctuation = (text) => {
    if (!text) return "";
    return text.replace(/[.,?!]/g, "");
};

// [Add] 레거시 데이터(과거 분석 기록) 제목 정규화 유틸리티
const normalizeLegacyTitle = (title) => {
    if (!title) return "제목 없음";
    let clean = title;
    clean = clean.replace(/^[0-9a-fA-F]{8}_/, "");
    clean = clean.replace(/\.[^/.]+$/, "");
    clean = clean.replace(/_/g, " ");
    return clean.trim();
};

// --- [Sub Component] Task Monitor Widget (Upgraded v2) ---
function TaskMonitor({ tasks, onCancel }) {
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
}

// 구간 시각화 컴포넌트 (타임라인 바)
const TimelineVisualizer = ({ totalDuration, start, end }) => {
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

// --- [Sub Component] Segmented Control (Slide Tab) ---
function SegmentedControl({ activeTab, onChange }) {
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
}
