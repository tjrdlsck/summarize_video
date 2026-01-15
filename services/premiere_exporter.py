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
    [Feature] AI Marker 및 편집 지시문 자동 삽입 지원.
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

    def _create_marker_xml(self, seg, fps):
        """
        클립 아이템 내부에 마커 정보를 생성합니다.
        """
        markers_xml = ""
        # 1. 챕터 요약 마커
        if seg.get('summary'):
            markers_xml += f"""
            <marker>
                <name>[AI 요약] {seg.get('title', 'Highlight')}</name>
                <comment>{seg['summary']}</comment>
                <in>0</in>
                <out>0</out>
            </marker>"""
        
        # 2. 편집 가이드 마커 (중요)
        if seg.get('edit_guide'):
            markers_xml += f"""
            <marker>
                <name>✂️ 편집 지시문</name>
                <comment>{seg['edit_guide']}</comment>
                <in>0</in>
                <out>0</out>
            </marker>"""
            
        return markers_xml

    def _create_clip_item(self, idx, track_type, meta, video_name, 
                          file_id, master_clip_id, is_file_defined, relative_filename,
                          duration_frame, current_timeline_frame, in_frame, out_frame, 
                          audio_source_channel=1, link_ids=None, seg_data=None):
        """
        [Helper] 클립 아이템 생성.
        """
        suffix = f"-{audio_source_channel}" if track_type == "audio" else ""
        clip_id = f"clipitem-{idx+1}-{track_type}{suffix}" 
        
        if not is_file_defined:
            file_node = f'<file id="{file_id}"/>'
        else:
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

        sourcetrack = ""
        if track_type == "audio":
            sourcetrack = f"""
            <sourcetrack>
                <mediatype>audio</mediatype>
                <trackindex>{audio_source_channel}</trackindex>
            </sourcetrack>
            """

        links_xml = ""
        if link_ids:
            for link in link_ids:
                group_attr = ' <groupindex>1</groupindex>' if link['type'] == 'audio' else ''
                links_xml += f"""
                <link>
                    <linkclipref>{link['id']}</linkclipref>
                    <mediatype>{link['type']}</mediatype>
                    <trackindex>{link['trackindex']}</trackindex>
                    <clipindex>{link['clipindex']}</clipindex>{group_attr}
                </link>
                """

        # 마커 추가 (비디오 트랙에만 표시)
        markers_xml = ""
        if track_type == "video" and seg_data:
            markers_xml = self._create_marker_xml(seg_data, meta['fps'])

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
            <out>{out_frame} </out>
            {file_node}
            {sourcetrack}
            {links_xml}
            {markers_xml}
          </clipitem>
        """

    def create_xml(self, video_path, segments, output_filename="export.xml", video_name=None):
        meta = self._get_video_info(video_path)
        server_filename = os.path.basename(video_path)
        
        if video_name:
            base_name = video_name
            ext = os.path.splitext(server_filename)[1]
            if not base_name.lower().endswith(ext.lower()):
                original_filename = base_name + ext
            else:
                original_filename = base_name
        else:
            if re.match(r'^[0-9a-fA-F]{8}_', server_filename):
                guessed_name = server_filename[9:] 
            else:
                guessed_name = server_filename
            name_part, ext_part = os.path.splitext(guessed_name)
            original_filename = name_part.replace('_', ' ') + ext_part
        
        original_filename = original_filename.strip()

        video_uuid = str(uuid.uuid4())
        file_id = f"file-{video_uuid}"
        master_clip_id = f"masterclip-{video_uuid}"
        
        video_track_items = []
        audio_tracks_items = [[] for _ in range(meta['channels'])]
        
        current_timeline_frame = 0 
        file_defined_flag = False  
        
        for idx, seg in enumerate(segments):
            start_sec = seg['start']
            end_sec = seg['end']
            
            in_frame = self._sec_to_frame(start_sec, meta['fps'])
            out_frame = self._sec_to_frame(end_sec, meta['fps'])
            duration_frame = out_frame - in_frame
            
            if duration_frame <= 0: continue

            clip_index = idx + 1
            vid_id = f"clipitem-{idx+1}-video"
            aud_ids = []
            for ch in range(meta['channels']):
                aud_ids.append(f"clipitem-{idx+1}-audio-{ch+1}")

            links = []
            links.append({'id': vid_id, 'type': 'video', 'trackindex': 1, 'clipindex': clip_index})
            for i, aid in enumerate(aud_ids):
                links.append({'id': aid, 'type': 'audio', 'trackindex': i + 1, 'clipindex': clip_index})
            
            is_file_def = not file_defined_flag
            if is_file_def: file_defined_flag = True
            
            v_item = self._create_clip_item(
                idx, "video", meta, original_filename, 
                file_id, master_clip_id, is_file_def, original_filename,
                duration_frame, current_timeline_frame, in_frame, out_frame,
                link_ids=links, seg_data=seg # 세그먼트 데이터 전달 (마커용)
            )
            video_track_items.append(v_item)
            
            for ch_idx in range(meta['channels']):
                a_item = self._create_clip_item(
                    idx, "audio", meta, original_filename, 
                    file_id, master_clip_id, False, original_filename,
                    duration_frame, current_timeline_frame, in_frame, out_frame,
                    audio_source_channel=ch_idx + 1,
                    link_ids=links
                )
                audio_tracks_items[ch_idx].append(a_item)
            
            current_timeline_frame += duration_frame

        header = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE xmeml>',
            '<xmeml version="4">',
            '  <sequence>',
            '    <name>AI_Longform_Sequence</name>',
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
            
        print(f"--- [Exporter] XML Generated with Markers: {output_path} ---")
        return output_path