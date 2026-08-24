'use client';

import React from 'react';
import { ArrowRight, Download, Film, Loader2 } from 'lucide-react';
import type { StageViewProps } from './types';
import { assetUrl } from './utils';
import StageProgress from './StageProgress';
import StageActions from './StageActions';

interface PostProductionStageProps extends StageViewProps {
  creationMode?: 'trial' | 'full' | 'expanded';
  onExpandTrial?: () => void;
}

export default function PostProductionStage({ state, onConfirm, onRegenerate, isRunning, hasPendingItems, hasNextStageStarted, artifacts, scriptArtifact, creationMode, onExpandTrial }: PostProductionStageProps) {
  // 提取最终视频列表
  const finalVideos: any[] = React.useMemo(
    () => state.artifact?.final_videos || [],
    [state.artifact?.final_videos],
  );
  
  // 兼容旧格式及其变形
  const legacyVideo = state.artifact?.final_video;
  
  // 从剧本或分镜数据中提取剧集名称映射
  const episodeTitleMap = React.useMemo(() => {
    // 优先从 scriptArtifact 获取
    const episodes = scriptArtifact?.episodes || artifacts?.storyboard?.episodes || artifacts?.script?.episodes || [];
    const map: Record<number, string> = {};
    episodes.forEach((ep: any) => {
      const epNum = ep.episode_number || ep.episode;
      if (epNum) {
        map[Number(epNum)] = ep.act_title || ep.title || '';
      }
    });
    return map;
  }, [artifacts, scriptArtifact]);
  
  // 确保能拿到展示数据
  const videosToDisplay = React.useMemo(() => {
    if (finalVideos && finalVideos.length > 0) return finalVideos;
    if (legacyVideo) return [{ name: '最终成片', path: legacyVideo, episode: 1 }];
    return [];
  }, [finalVideos, legacyVideo]);
  const trialDuration = Math.max(1, Number(artifacts?.storyboard?.trial_duration_seconds || 15));

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 min-w-0 overflow-y-auto p-4 sm:p-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-1">后期剪辑</h2>
        <p className="text-sm text-gray-500 mb-6">
          {creationMode === 'trial' ? `${trialDuration}秒轻量试片已完成，可先验证风格和人物表现` : '按剧集拼接视频，生成各集独立成片'}
        </p>

        {/* 运行中 */}
        {state.status === 'running' && (
          <StageProgress message={state.progressMessage} fallback="正在合成视频..." progress={state.progress} color="cyan" />
        )}

        {state.error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-4 rounded-xl mb-4">{state.error}</div>
        )}

        {/* 最终视频列表 */}
        {videosToDisplay.length > 0 && (
          <div className="space-y-10 pb-10">
            {videosToDisplay.map((video, idx) => {
              const epNum = video.episode || (idx + 1);
              const scriptTitle = episodeTitleMap[epNum];
              const epTitle = scriptTitle ? `第 ${epNum} 集：${scriptTitle}` : (video.name || `第 ${epNum} 集`);
              
              return (
                <div key={idx} className="space-y-4">
                  {/* 剧集分割行 - 完全同步 S4/S5 格式 */}
                  <div className="flex flex-wrap items-center justify-between gap-3 py-2 px-1 border-b border-gray-100">
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="w-1.5 h-6 bg-cyan-500 rounded-full" />
                      <h3 className="min-w-0 text-base font-bold text-gray-800">{epTitle}</h3>
                    </div>
                  </div>
                  
                  <div className="bg-black rounded-xl overflow-hidden shadow-lg border border-gray-800">
                    <video 
                      src={assetUrl(video.path)} 
                      controls 
                      className="w-full max-h-[60vh] object-contain" 
                    />
                  </div>
                  
                  <div className="flex items-center justify-end">
                    <a
                      href={assetUrl(video.path)}
                      download={`${epTitle}.mp4`}
                      className="flex items-center gap-2 px-4 py-2 bg-gray-800 text-white rounded-lg text-xs font-medium hover:bg-black transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                      下载本集
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {creationMode === 'trial' && videosToDisplay.length > 0 && (
          <section className="mb-10 rounded-2xl bg-blue-50 p-5 sm:flex sm:items-center sm:justify-between sm:gap-6">
            <div className="max-w-2xl">
              <h3 className="text-base font-semibold text-blue-950">这支试片可以直接交付，也可以继续长成完整一集</h3>
              <p className="mt-1 text-sm leading-6 text-blue-800">
                扩展会保留当前{trialDuration}秒作为开场，复用已有角色、场景、首帧和视频，只生成后续缺少的内容。
              </p>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 sm:mt-0 sm:shrink-0">
              <a
                href={assetUrl(videosToDisplay[0].path)}
                download={`导梦-${trialDuration}秒试片.mp4`}
                className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-medium text-blue-800 shadow-sm hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <Download className="h-4 w-4" />
                导出{trialDuration}秒试片
              </a>
              <button
                type="button"
                onClick={onExpandTrial}
                disabled={isRunning}
                className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:bg-blue-300"
              >
                {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                {isRunning ? '正在扩展…' : '扩展为1–2分钟完整一集'}
              </button>
            </div>
          </section>
        )}

        {state.status === 'completed' && videosToDisplay.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <Film className="w-12 h-12 mb-3" />
            <div className="text-sm">视频合成完成</div>
          </div>
        )}

        {state.status === 'pending' && (
          <div className="text-center text-gray-400 text-sm py-20">等待上一阶段完成...</div>
        )}
      </div>

      <StageActions
        status={state.status}
        onConfirm={onConfirm}
        showConfirm={false}
        onRegenerate={onRegenerate}
        stageId="post_production"
        hasPendingItems={hasPendingItems}
        hasNextStageStarted={hasNextStageStarted}
        isRunning={isRunning}
      />
    </div>
  );
}
