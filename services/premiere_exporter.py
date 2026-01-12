import os
import uuid
import subprocess
import json
import math
import re
import urllib.parse

class PremiereExporter:
    """
    영상 파일과 구간(Segment) 정보를 받아 Adobe Premiere Pro 호환 XML(FCP7 포맷)을 생성하는 클래스.
    [Feature] Stereo/Multi-channel Audio 지원.
    [Feature] 완벽한 Video-Audio Link (Clipindex, Groupindex, Masterclipid) 지원.
    [Optimization] File Node 참조 최적화 (Reference mode).
    """
    
    def __init__(self, output_dir="static/temp"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_video_info(self, video_path):
        """
        ffprobe를 사용하여 영상 및 오디오 정보를 추출합니다.
        """
        try:
            cmd = [
                "ffprobe", 
                "-v", "error", 
                "-show_entries", "stream=width,height,r_frame_rate,duration,nb_frames,channels,codec_type",
                "-of", "json",
                video_path
            ]
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            info = json.loads(result.stdout)
            
            width = 1920
            height = 1080
            fps = 30.0
            duration = 0.0
            total_frames = 0
            channels = 2
            
            for stream in info.get('streams', []):
                if stream['codec_type'] == 'video':
                    width = int(stream.get('width', width))
                    height = int(stream.get('height', height))
                    r_frame_rate = stream.get('r_frame_rate', '30/1')
                    try:
                        num, den = map(int, r_frame_rate.split('/'))
                        fps = num / den
                    except:
                        fps = 30.0
                    
                    duration = float(stream.get('duration', duration))
                    total_frames = int(stream.get('nb_frames', total_frames))
                
                elif stream['codec_type'] == 'audio':
                    c = int(stream.get('channels', 0))
                    if c > 0:
                        channels = c

            timebase = int(round(fps))
            ntsc = "TRUE" if (timebase != fps) else "FALSE"
            
            return {
                "width": width,
                "height": height,
                "fps": fps,
                "timebase": timebase,
                "ntsc": ntsc,
                "duration_sec": duration,
                "total_frames": total_frames,
                "channels": channels
            }
            
        except Exception as e:
            print(f"[Exporter Error] Failed to probe video info: {e}")
            return {
                "width": 1920, "height": 1080, "fps": 30.0, 
                "timebase": 30, "ntsc": "FALSE", "duration_sec": 0, "total_frames": 0,
                "channels": 2
            }

    def _sec_to_frame(self, seconds, fps):
        return int(round(seconds * fps))

    def _create_clip_item(self, idx, track_type, meta, video_name, 
                          file_id, master_clip_id, is_file_defined, relative_filename,
                          duration_frame, current_timeline_frame, in_frame, out_frame, 
                          audio_source_channel=1, link_ids=None):
        """
        [Helper] 클립 아이템 생성.
        - file_id: 모든 클립이 공유하는 파일 ID
        - master_clip_id: 모든 클립이 공유하는 마스터 클립 ID
        - is_file_defined: True면 <file> 내용을 전체 기록, False면 <file id="..."/> 참조만 기록
        - link_ids: 링크 정보 리스트
        """
        # 고유 ID 생성
        suffix = f"-{audio_source_channel}" if track_type == "audio" else ""
        clip_id = f"clipitem-{idx+1}-{track_type}{suffix}" 
        
        # 1. 미디어 특성 (Media Characteristics)
        # XML 구조상 <file> 내부에 media가 있지만, clipitem 직계 자식으로도 media 정보를 일부 가질 수 있음.
        # test2.xml 패턴을 따름.
        # 그러나 test2.xml은 clipitem 내부에 media 관련 태그를 크게 두지 않고 file 내부에 둠.
        # 여기서는 최소한의 정보만 남기거나 생략 가능하지만, 안전을 위해 유지.
        
        # 2. 파일 노드 (File Node)
        if not is_file_defined:
            # 이미 정의된 파일 참조
            file_node = f'<file id="{file_id}"/>'
        else:
            # 최초 파일 정의 (Full Definition)
            encoded_filename = urllib.parse.quote(relative_filename)
            file_node = f"""
            <file id="{file_id}">
              <name>{video_name}</name>
              <pathurl>file://localhost/{encoded_filename}</pathurl>
              <rate>
                <timebase>{meta['timebase']}</timebase>
                <ntsc>{meta['ntsc']}</ntsc>
              </rate>
              <duration>{meta['total_frames']}</duration>
              <media>
                <video>
                  <samplecharacteristics>
                    <width>{meta['width']}</width>
                    <height>{meta['height']}</height>
                  </samplecharacteristics>
                </video>
                <audio>
                  <samplecharacteristics>
                    <depth>16</depth>
                    <samplerate>48000</samplerate>
                  </samplecharacteristics>
                  <channelcount>{meta['channels']}</channelcount>
                </audio>
              </media>
            </file>
            """

        # 3. 소스 트랙 매핑
        sourcetrack = ""
        if track_type == "audio":
            sourcetrack = f"""
            <sourcetrack>
                <mediatype>audio</mediatype>
                <trackindex>{audio_source_channel}</trackindex>
            </sourcetrack>
            """

        # 4. 링크 (Links)
        links_xml = ""
        if link_ids:
            for link in link_ids:
                # 오디오 링크인 경우 groupindex="1" 추가 (test2.xml 분석 결과)
                group_attr = ' <groupindex>1</groupindex>' if link['type'] == 'audio' else ''
                
                links_xml += f"""
                <link>
                    <linkclipref>{link['id']}</linkclipref>
                    <mediatype>{link['type']}</mediatype>
                    <trackindex>{link['trackindex']}</trackindex>
                    <clipindex>{link['clipindex']}</clipindex>{group_attr}
                </link>
                """

        # 마스터 클립 ID 추가
        master_clip_node = f"<masterclipid>{master_clip_id}</masterclipid>" if master_clip_id else ""

        return f"""
          <clipitem id="{clip_id}">
            {master_clip_node}
            <name>{video_name}</name>
            <enabled>TRUE</enabled>
            <duration>{duration_frame}</duration>
            <rate>
              <timebase>{meta['timebase']}</timebase>
              <ntsc>{meta['ntsc']}</ntsc>
            </rate>
            <start>{current_timeline_frame}</start>
            <end>{current_timeline_frame + duration_frame}</end>
            <in>{in_frame}</in>
            <out>{out_frame}</out>
            {file_node}
            {sourcetrack}
            {links_xml}
          </clipitem>
        """

    def create_xml(self, video_path, segments, output_filename="export.xml"):
        meta = self._get_video_info(video_path)
        
        server_filename = os.path.basename(video_path)
        original_filename = re.sub(r'^[0-9a-fA-F]{8}_', '', server_filename)
        
        # 공통 ID 생성
        video_uuid = str(uuid.uuid4())
        file_id = f"file-{video_uuid}"
        master_clip_id = f"masterclip-{video_uuid}"
        
        video_track_items = []
        audio_tracks_items = [[] for _ in range(meta['channels'])]
        
        current_timeline_frame = 0 
        file_defined_flag = False  # 파일을 XML에 한 번이라도 썼는지 체크
        
        for idx, seg in enumerate(segments):
            start_sec = seg['start']
            end_sec = seg['end']
            
            in_frame = self._sec_to_frame(start_sec, meta['fps'])
            out_frame = self._sec_to_frame(end_sec, meta['fps'])
            duration_frame = out_frame - in_frame
            
            if duration_frame <= 0: continue

            # Clip Index: 트랙 내에서 몇 번째 클립인가? (1-based)
            clip_index = idx + 1

            # --- ID 미리 생성 ---
            vid_id = f"clipitem-{idx+1}-video"
            aud_ids = []
            for ch in range(meta['channels']):
                aud_ids.append(f"clipitem-{idx+1}-audio-{ch+1}")

            # --- Link 정보 구성 (test2.xml 로직 적용) ---
            # 모든 링크는 trackindex와 clipindex를 가져야 함.
            links = []
            
            # 1. Video Link info
            links.append({
                'id': vid_id, 
                'type': 'video', 
                'trackindex': 1, 
                'clipindex': clip_index
            })
            
            # 2. Audio Links info
            for i, aid in enumerate(aud_ids):
                links.append({
                    'id': aid, 
                    'type': 'audio', 
                    'trackindex': i + 1, 
                    'clipindex': clip_index
                })
            
            # --- 비디오 아이템 생성 ---
            # 첫 번째 아이템(보통 비디오 첫 컷)에서 파일 정의를 수행
            is_file_def = not file_defined_flag
            if is_file_def: file_defined_flag = True
            
            v_item = self._create_clip_item(
                idx, "video", meta, original_filename, 
                file_id, master_clip_id, is_file_def, original_filename,
                duration_frame, current_timeline_frame, in_frame, out_frame,
                link_ids=links
            )
            video_track_items.append(v_item)
            
            # --- 오디오 아이템 생성 ---
            for ch_idx in range(meta['channels']):
                # 파일은 이미 비디오에서 정의되었으므로 False
                # (만약 비디오 트랙이 없는 예외 상황이라면 여기서 정의해야 하겠지만, 보통 비디오는 존재함)
                a_item = self._create_clip_item(
                    idx, "audio", meta, original_filename, 
                    file_id, master_clip_id, False, original_filename,
                    duration_frame, current_timeline_frame, in_frame, out_frame,
                    audio_source_channel=ch_idx + 1,
                    link_ids=links
                )
                audio_tracks_items[ch_idx].append(a_item)
            
            current_timeline_frame += duration_frame

        # XML 조립
        header = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE xmeml>',
            '<xmeml version="4">',
            '  <sequence>',
            '    <name>AI_Shorts_Sequence</name>',
            f'    <duration>{current_timeline_frame}</duration>',
            '    <rate>',
            f'      <timebase>{meta["timebase"]}</timebase>',
            f'      <ntsc>{meta["ntsc"]}</ntsc>',
            '    </rate>',
            '    <media>'
        ]
        
        video_block = [
            '      <video>',
            '        <format>',
            '          <samplecharacteristics>',
            '            <rate>',
            f'              <timebase>{meta["timebase"]}</timebase>',
            f'              <ntsc>{meta["ntsc"]}</ntsc>',
            '            </rate>',
            f'            <width>{meta["width"]}</width>',
            f'            <height>{meta["height"]}</height>',
            '            <pixelaspectratio>square</pixelaspectratio>',
            '          </samplecharacteristics>',
            '        </format>',
            '        <track>'
        ] + video_track_items + [
            '        </track>',
            '      </video>'
        ]
        
        audio_block = ['      <audio>']
        for i, track_items in enumerate(audio_tracks_items):
            audio_block.append('        <track>')
            audio_block.extend(track_items)
            audio_block.append('        </track>')
        audio_block.append('      </audio>')
        
        footer = [
            '    </media>',
            '  </sequence>',
            '</xmeml>'
        ]
        
        final_xml_str = "\n".join(header + video_block + audio_block + footer)
        
        output_path = os.path.join(self.output_dir, output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_xml_str)
            
        print(f"--- [Exporter] XML Generated (Full Link Support): {output_path} ---")
        return output_path