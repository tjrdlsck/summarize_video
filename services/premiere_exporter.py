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
    [Update] 경로 방식을 '상대 경로(./)'로 변경하여, XML과 영상이 같은 폴더에 있을 때 
    100% 자동 연결되도록 개선했습니다.
    """
    
    def __init__(self, output_dir="static/temp"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_video_info(self, video_path):
        """
        ffprobe를 사용하여 영상의 FPS, 해상도, 오디오 샘플 레이트 등을 추출합니다.
        """
        try:
            cmd = [
                "ffprobe", 
                "-v", "error", 
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,duration,nb_frames",
                "-of", "json",
                video_path
            ]
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            info = json.loads(result.stdout)
            
            stream = info['streams'][0]
            width = int(stream['width'])
            height = int(stream['height'])
            
            r_frame_rate = stream['r_frame_rate']
            num, den = map(int, r_frame_rate.split('/'))
            fps = num / den
            
            timebase = int(round(fps))
            ntsc = "TRUE" if (timebase != fps) else "FALSE"
            
            return {
                "width": width,
                "height": height,
                "fps": fps,
                "timebase": timebase,
                "ntsc": ntsc,
                "duration_sec": float(stream.get('duration', 0)),
                "total_frames": int(stream.get('nb_frames', 0))
            }
            
        except Exception as e:
            print(f"[Exporter Error] Failed to probe video info: {e}")
            return {
                "width": 1920, "height": 1080, "fps": 30.0, 
                "timebase": 30, "ntsc": "FALSE", "duration_sec": 0, "total_frames": 0
            }

    def _sec_to_frame(self, seconds, fps):
        return int(round(seconds * fps))

    def _create_clip_item(self, idx, track_type, meta, video_name, video_uuid, relative_filename, duration_frame, current_timeline_frame, in_frame, out_frame):
        """
        [Helper] 클립 아이템 생성. 
        [Fix] macOS 호환성을 위해 파일명을 URL 인코딩(Percent Encoding) 처리합니다.
        맥은 경로 내의 특수문자나 공백 처리에 매우 엄격하므로 이 처리가 필수적입니다.
        """
        clip_id = f"clipitem-{track_type}-{idx+1}"
        
        media_xml = ""
        if track_type == "video":
            media_xml = f"""
                <video>
                  <samplecharacteristics>
                    <width>{meta['width']}</width>
                    <height>{meta['height']}</height>
                  </samplecharacteristics>
                </video>
            """
        else:
            media_xml = """
                <audio>
                  <samplecharacteristics>
                    <depth>16</depth>
                    <samplerate>48000</samplerate>
                  </samplecharacteristics>
                </audio>
            """

        # [핵심 변경 포인트]
        # 1. 파일명을 URL 인코딩합니다. (예: "My Video.mp4" -> "My%20Video.mp4")
        encoded_filename = urllib.parse.quote(relative_filename)
        
        # 2. file://localhost/ 뒤에 인코딩된 파일명을 붙입니다.
        # 이렇게 하면 macOS에서도 문법적으로 완벽한 URI로 인식하여 파싱 오류를 방지합니다.
        file_node = f"""
            <file id="file-{video_uuid}">
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
                </audio>
              </media>
            </file>
        """

        sourcetrack = ""
        if track_type == "audio":
            sourcetrack = """
            <sourcetrack>
                <mediatype>audio</mediatype>
                <trackindex>1</trackindex>
            </sourcetrack>
            """

        return f"""
          <clipitem id="{clip_id}">
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
          </clipitem>
        """

    def create_xml(self, video_path, segments, output_filename="export.xml"):
        meta = self._get_video_info(video_path)
        
        # 1. 파일명 정제 (UUID 제거하여 원본 파일명 추출)
        server_filename = os.path.basename(video_path)
        original_filename = re.sub(r'^[0-9a-fA-F]{8}_', '', server_filename)
        
        # 2. 상대 경로용 파일명 준비
        # 이전에는 fake_abs_path(절대경로)를 만들었지만, 
        # 이제는 단순히 파일명(original_filename)만 있으면 됩니다.
        
        video_uuid = str(uuid.uuid4())
        
        video_track_items = []
        audio_track_items = []
        
        current_timeline_frame = 0 
        
        for idx, seg in enumerate(segments):
            start_sec = seg['start']
            end_sec = seg['end']
            
            in_frame = self._sec_to_frame(start_sec, meta['fps'])
            out_frame = self._sec_to_frame(end_sec, meta['fps'])
            duration_frame = out_frame - in_frame
            
            if duration_frame <= 0: continue

            # 비디오 클립 (파일명만 전달)
            v_item = self._create_clip_item(
                idx, "video", meta, original_filename, video_uuid, original_filename,
                duration_frame, current_timeline_frame, in_frame, out_frame
            )
            video_track_items.append(v_item)
            
            # 오디오 클립 (파일명만 전달)
            a_item = self._create_clip_item(
                idx, "audio", meta, original_filename, video_uuid, original_filename,
                duration_frame, current_timeline_frame, in_frame, out_frame
            )
            audio_track_items.append(a_item)
            
            current_timeline_frame += duration_frame

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
        
        audio_block = [
            '      <audio>',
            '        <track>'
        ] + audio_track_items + [
            '        </track>',
            '      </audio>'
        ]
        
        footer = [
            '    </media>',
            '  </sequence>',
            '</xmeml>'
        ]
        
        final_xml_str = "\n".join(header + video_block + audio_block + footer)
        
        output_path = os.path.join(self.output_dir, output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_xml_str)
            
        print(f"--- [Exporter] XML Generated (Relative Path): {output_path} ---")
        return output_path