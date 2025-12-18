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
    [Fix] 오디오 샘플 레이트 불일치로 인한 다빈치 리졸브 오디오 누락 문제 해결
    """
    
    def __init__(self, output_dir="static/temp"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_video_info(self, video_path):
        """
        ffprobe를 사용하여 영상 정보를 추출하되, 
        [Mono Test] 오디오 채널을 강제로 1로 고정하여 XML이 모노로 생성되도록 유도합니다.
        """
        try:
            cmd = [
                "ffprobe", 
                "-v", "error", 
                "-show_entries", "stream=width,height,r_frame_rate,duration,nb_frames,sample_rate,channels,bits_per_raw_sample,codec_name,codec_type",
                "-of", "json",
                video_path
            ]
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            info = json.loads(result.stdout)
            
            # 스트림 분류
            v_stream = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
            a_stream = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)

            # 비디오 정보
            width = 1920
            height = 1080
            fps = 30.0
            duration_sec = 0.0
            total_frames = 0

            if v_stream:
                width = int(v_stream.get('width', 1920))
                height = int(v_stream.get('height', 1080))
                
                r_frame_rate = v_stream.get('r_frame_rate', '30/1')
                num, den = map(int, r_frame_rate.split('/'))
                fps = num / den if den != 0 else 30.0
                
                duration_sec = float(v_stream.get('duration', 0))
                total_frames = int(v_stream.get('nb_frames', 0))
                
                if total_frames == 0 and duration_sec > 0:
                    total_frames = int(duration_sec * fps)

            timebase = int(round(fps))
            ntsc = "TRUE" if (timebase != fps) else "FALSE"

            # [Mono Force Fix] 오디오 정보 추출
            audio_rate = 48000
            audio_depth = 16
            audio_channels = 1  # [강제 변경] 실제 파일이 2채널이어도 1채널로 인식시킴
            
            if a_stream:
                audio_rate = int(a_stream.get('sample_rate', 48000))
                audio_depth = int(a_stream.get('bits_per_raw_sample', 16))
                if audio_depth == 0: audio_depth = 16
                # audio_channels = int(a_stream.get('channels', 2)) -> 사용 안 함

            return {
                "width": width,
                "height": height,
                "fps": fps,
                "timebase": timebase,
                "ntsc": ntsc,
                "duration_sec": duration_sec,
                "total_frames": total_frames,
                "audio_rate": audio_rate,   
                "audio_depth": audio_depth,
                "audio_channels": audio_channels # 1로 고정됨
            }
            
        except Exception as e:
            print(f"[Exporter Error] Failed to probe video info: {e}")
            return {
                "width": 1920, "height": 1080, "fps": 30.0, 
                "timebase": 30, "ntsc": "FALSE", "duration_sec": 0, "total_frames": 0,
                "audio_rate": 48000, "audio_depth": 16, "audio_channels": 1 # 오류 시에도 1채널
            }

    def _sec_to_frame(self, seconds, fps):
        return int(round(seconds * fps))

    def _create_clip_item(self, idx, track_type, meta, video_name, video_uuid, relative_filename, duration_frame, current_timeline_frame, in_frame, out_frame):
        clip_id = f"clipitem-{track_type}-{idx+1}"
        encoded_filename = urllib.parse.quote(relative_filename)
        
        # [수정] XML 내 오디오 정보를 메타데이터(meta) 기반으로 동적 생성 + channelcount 추가
        # File 노드 내부의 media 정의
        media_xml = ""
        if track_type == "video":
            media_xml = f"""
                <video>
                  <samplecharacteristics>
                    <width>{meta['width']}</width>
                    <height>{meta['height']}</height>
                  </samplecharacteristics>
                </video>
                <audio>
                  <samplecharacteristics>
                    <depth>{meta['audio_depth']}</depth>
                    <samplerate>{meta['audio_rate']}</samplerate>
                    <channelcount>{meta['audio_channels']}</channelcount>
                  </samplecharacteristics>
                </audio>
            """
        else:
            # 오디오 트랙용 미디어 정의도 동일하게 가져감 (Source File은 하나이므로)
            media_xml = f"""
                <video>
                  <samplecharacteristics>
                    <width>{meta['width']}</width>
                    <height>{meta['height']}</height>
                  </samplecharacteristics>
                </video>
                <audio>
                  <samplecharacteristics>
                    <depth>{meta['audio_depth']}</depth>
                    <samplerate>{meta['audio_rate']}</samplerate>
                    <channelcount>{meta['audio_channels']}</channelcount>
                  </samplecharacteristics>
                </audio>
            """

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
                {media_xml}
              </media>
            </file>
        """

        # [수정] 소스 트랙 매핑 로직 개선 (Stereo 지원)
        sourcetrack = ""
        if track_type == "audio":
            # 채널 수만큼 반복하여 소스 트랙 매핑 생성
            # 예: Stereo(2ch) -> sourcetrack 1, sourcetrack 2 생성하여 스테레오 클립으로 인식 유도
            tracks_xml = ""
            for ch in range(1, meta['audio_channels'] + 1):
                tracks_xml += f"""
                <sourcetrack>
                    <mediatype>audio</mediatype>
                    <trackindex>{ch}</trackindex>
                </sourcetrack>
                """
            sourcetrack = tracks_xml

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
        
        server_filename = os.path.basename(video_path)
        original_filename = re.sub(r'^[0-9a-fA-F]{8}_', '', server_filename)
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

            v_item = self._create_clip_item(
                idx, "video", meta, original_filename, video_uuid, original_filename,
                duration_frame, current_timeline_frame, in_frame, out_frame
            )
            video_track_items.append(v_item)
            
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
            
        print(f"--- [Exporter] XML Generated: {output_path} ---")
        return output_path

    def _get_label_index(self, category):
        mapping = {
            "Hook": 6, "Story": 1, "Insight": 7, "B-Roll": 3
        }
        return mapping.get(category, 0)

    def _get_default_video_filters(self, duration_frame):
        """
        [Helper] 다빈치 리졸브(Timeline 1.xml) 스타일의 기본 비디오 필터(Motion, Crop, Opacity)를 생성합니다.
        """
        return f"""
            <compositemode>normal</compositemode>
            <filter>
                <enabled>TRUE</enabled>
                <start>0</start>
                <end>{duration_frame}</end>
                <effect>
                    <name>Basic Motion</name>
                    <effectid>basic</effectid>
                    <effecttype>motion</effecttype>
                    <mediatype>video</mediatype>
                    <effectcategory>motion</effectcategory>
                    <parameter>
                        <name>Scale</name>
                        <parameterid>scale</parameterid>
                        <value>100</value>
                        <valuemin>0</valuemin>
                        <valuemax>10000</valuemax>
                    </parameter>
                    <parameter>
                        <name>Center</name>
                        <parameterid>center</parameterid>
                        <value>
                            <horiz>0</horiz>
                            <vert>0</vert>
                        </value>
                    </parameter>
                    <parameter>
                        <name>Rotation</name>
                        <parameterid>rotation</parameterid>
                        <value>0</value>
                        <valuemin>-100000</valuemin>
                        <valuemax>100000</valuemax>
                    </parameter>
                    <parameter>
                        <name>Anchor Point</name>
                        <parameterid>centerOffset</parameterid>
                        <value>
                            <horiz>0</horiz>
                            <vert>0</vert>
                        </value>
                    </parameter>
                </effect>
            </filter>
            <filter>
                <enabled>TRUE</enabled>
                <start>0</start>
                <end>{duration_frame}</end>
                <effect>
                    <name>Crop</name>
                    <effectid>crop</effectid>
                    <effecttype>motion</effecttype>
                    <mediatype>video</mediatype>
                    <effectcategory>motion</effectcategory>
                    <parameter>
                        <name>left</name>
                        <parameterid>left</parameterid>
                        <value>0</value>
                        <valuemin>0</valuemin>
                        <valuemax>100</valuemax>
                    </parameter>
                    <parameter>
                        <name>right</name>
                        <parameterid>right</parameterid>
                        <value>0</value>
                        <valuemin>0</valuemin>
                        <valuemax>100</valuemax>
                    </parameter>
                    <parameter>
                        <name>top</name>
                        <parameterid>top</parameterid>
                        <value>0</value>
                        <valuemin>0</valuemin>
                        <valuemax>100</valuemax>
                    </parameter>
                    <parameter>
                        <name>bottom</name>
                        <parameterid>bottom</parameterid>
                        <value>0</value>
                        <valuemin>0</valuemin>
                        <valuemax>100</valuemax>
                    </parameter>
                </effect>
            </filter>
            <filter>
                <enabled>TRUE</enabled>
                <start>0</start>
                <end>{duration_frame}</end>
                <effect>
                    <name>Opacity</name>
                    <effectid>opacity</effectid>
                    <effecttype>motion</effecttype>
                    <mediatype>video</mediatype>
                    <effectcategory>motion</effectcategory>
                    <parameter>
                        <name>opacity</name>
                        <parameterid>opacity</parameterid>
                        <value>100</value>
                        <valuemin>0</valuemin>
                        <valuemax>100</valuemax>
                    </parameter>
                </effect>
            </filter>
        """
    
    def _get_default_audio_filters(self, duration_frame):
        """
        [Helper] 다빈치 리졸브(Timeline 1.xml) 스타일의 기본 오디오 필터(Levels, Pan)를 생성합니다.
        """
        return f"""
            <filter>
                <enabled>TRUE</enabled>
                <start>0</start>
                <end>{duration_frame}</end>
                <effect>
                    <name>Audio Levels</name>
                    <effectid>audiolevels</effectid>
                    <effecttype>audiolevels</effecttype>
                    <mediatype>audio</mediatype>
                    <effectcategory>audiolevels</effectcategory>
                    <parameter>
                        <name>Level</name>
                        <parameterid>level</parameterid>
                        <value>1</value>
                        <valuemin>0.00001</valuemin>
                        <valuemax>1000</valuemax>
                    </parameter>
                </effect>
            </filter>
            <filter>
                <enabled>TRUE</enabled>
                <start>0</start>
                <end>{duration_frame}</end>
                <effect>
                    <name>Audio Pan</name>
                    <effectid>audiopan</effectid>
                    <effecttype>audiopan</effecttype>
                    <mediatype>audio</mediatype>
                    <effectcategory>audiopan</effectcategory>
                    <parameter>
                        <name>Pan</name>
                        <parameterid>pan</parameterid>
                        <value>0</value>
                        <valuemin>-1</valuemin>
                        <valuemax>1</valuemax>
                    </parameter>
                </effect>
            </filter>
        """

    # [수정] 러프컷 생성 메서드도 동적 오디오 정보 반영
    def _create_rough_clip_item(self, 
                                clip_id, 
                                track_type, 
                                meta, 
                                video_name, 
                                video_uuid, 
                                relative_filename, 
                                start_sec, 
                                end_sec, 
                                current_tl_frame, 
                                category=None, 
                                title=None, 
                                reason=None, 
                                audio_channel_index=1,
                                link_data=None):
        
        in_frame = self._sec_to_frame(start_sec, meta['fps'])
        out_frame = self._sec_to_frame(end_sec, meta['fps'])
        duration_frame = out_frame - in_frame
        
        if duration_frame <= 0: return ""

        encoded_filename = urllib.parse.quote(relative_filename)

        # File Node (Timeline 1.xml 스타일: audio channelcount 명시 등)
        file_node = f"""
            <file id="file-{video_uuid}">
              <name>{video_name}</name>
              <pathurl>file://localhost/{encoded_filename}</pathurl>
              <rate>
                <timebase>{meta['timebase']}</timebase>
                <ntsc>{meta['ntsc']}</ntsc>
              </rate>
              <duration>{meta['total_frames']}</duration>
              <timecode>
                <string>00:00:00:00</string>
                <displayformat>NDF</displayformat>
                <rate>
                    <timebase>{meta['timebase']}</timebase>
                    <ntsc>{meta['ntsc']}</ntsc>
                </rate>
              </timecode>
              <media>
                <video>
                  <duration>{meta['total_frames']}</duration>
                  <samplecharacteristics>
                    <width>{meta['width']}</width>
                    <height>{meta['height']}</height>
                  </samplecharacteristics>
                </video>
                <audio>
                  <samplecharacteristics>
                    <depth>{meta['audio_depth']}</depth>
                    <samplerate>{meta['audio_rate']}</samplerate>
                    <channelcount>{meta['audio_channels']}</channelcount>
                  </samplecharacteristics>
                </audio>
              </media>
            </file>
        """

        # Labels & Markers (기존 로직 유지)
        labels_xml = ""
        marker_xml = ""
        if track_type == "video" and category:
            label_idx = self._get_label_index(category)
            # Resolve는 <labels> 태그를 덜 엄격하게 처리하지만 호환성을 위해 유지하거나 제거 가능
            # Timeline 1.xml에는 labels가 없으므로 여기서는 제거하지 않고 유지하되, 
            # 필요하다면 labels_xml = "" 로 비워도 됩니다.
            labels_xml = f"<labels><label2>{label_idx}</label2></labels>"
            if title and reason:
                safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                safe_reason = reason.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                marker_xml = f"""
                <marker>
                    <name>[{category}] {safe_title}</name>
                    <comment>{safe_reason}</comment>
                    <in>{in_frame}</in>
                    <out>{in_frame}</out>
                </marker>
                """

        # Sourcetrack (Timeline 1.xml 스타일)
        sourcetrack = ""
        if track_type == "audio":
            sourcetrack = f"""
            <sourcetrack>
                <mediatype>audio</mediatype>
                <trackindex>{audio_channel_index}</trackindex>
            </sourcetrack>
            """
        else:
            sourcetrack = f"""
            <sourcetrack>
                <mediatype>video</mediatype>
                <trackindex>1</trackindex>
            </sourcetrack>
            """

        # Link XML (Timeline 1.xml 스타일)
        link_xml = ""
        if link_data:
            for link_item in link_data:
                # mediatype 명시가 Resolve 호환성에 도움이 됨
                m_type = link_item.get('mediatype', 'video') 
                link_xml += f"""
                <link>
                    <linkclipref>{link_item['id']}</linkclipref>
                    <mediatype>{m_type}</mediatype>
                </link>
                """

        # [핵심] Filters 추가
        filters_xml = ""
        if track_type == "video":
            filters_xml = self._get_default_video_filters(duration_frame)
        elif track_type == "audio":
            filters_xml = self._get_default_audio_filters(duration_frame)

        return f"""
          <clipitem id="{clip_id}">
            <name>{video_name}</name>
            <enabled>TRUE</enabled>
            <duration>{duration_frame}</duration>
            <rate>
              <timebase>{meta['timebase']}</timebase>
              <ntsc>{meta['ntsc']}</ntsc>
            </rate>
            <start>{current_tl_frame}</start>
            <end>{current_tl_frame + duration_frame}</end>
            <in>{in_frame}</in>
            <out>{out_frame}</out>
            {file_node}
            {filters_xml}
            {labels_xml}
            {marker_xml}
            {sourcetrack}
            {link_xml}
          </clipitem>
        """

    def create_rough_cut_xml(self, video_path, selected_segments, output_filename="rough_cut.xml"):
        meta = self._get_video_info(video_path)
        
        server_filename = os.path.basename(video_path)
        original_filename = re.sub(r'^[0-9a-fA-F]{8}_', '', server_filename)
        video_uuid = str(uuid.uuid4())

        # V1: Full, A1: Full-L, A2: Full-R
        v1_items, a1_items, a2_items = [], [], []
        # V2: Cut, A3: Cut-L, A4: Cut-R
        v2_items, a3_items, a4_items = [], [], []

        # --- 1. 원본(Full) 트랙 생성 ---
        full_dur = meta['duration_sec']
        
        id_v1 = f"clipitem-video-full"
        id_a1 = f"clipitem-audio-full-L"
        id_a2 = f"clipitem-audio-full-R"
        
        link_full = [
            {'id': id_v1, 'mediatype': 'video', 'trackindex': 1},
            {'id': id_a1, 'mediatype': 'audio', 'trackindex': 1},
            {'id': id_a2, 'mediatype': 'audio', 'trackindex': 2}
        ]

        v1_items.append(self._create_rough_clip_item(
            id_v1, "video", meta, original_filename, video_uuid, original_filename, 0, full_dur, 0,
            link_data=link_full
        ))
        
        # A1 -> Source Track 1
        a1_items.append(self._create_rough_clip_item(
            id_a1, "audio", meta, original_filename, video_uuid, original_filename, 0, full_dur, 0,
            audio_channel_index=1, link_data=link_full
        ))
        
        # A2 -> Source Track 1 (or 2 if file has multiple tracks, but here we mirror Timeline 1 logic)
        a2_items.append(self._create_rough_clip_item(
            id_a2, "audio", meta, original_filename, video_uuid, original_filename, 0, full_dur, 0,
            audio_channel_index=1, link_data=link_full
        ))

        # --- 2. 편집(Cut) 트랙 생성 ---
        current_tl_frame = 0
        
        for idx, seg in enumerate(selected_segments):
            suffix = f"{idx}"
            id_v2 = f"clipitem-v2-{suffix}"
            id_a3 = f"clipitem-a3-{suffix}"
            id_a4 = f"clipitem-a4-{suffix}"
            
            link_cut = [
                {'id': id_v2, 'mediatype': 'video', 'trackindex': 2},
                {'id': id_a3, 'mediatype': 'audio', 'trackindex': 3},
                {'id': id_a4, 'mediatype': 'audio', 'trackindex': 4}
            ]

            # V2 Item
            v2_items.append(self._create_rough_clip_item(
                id_v2, "video", meta, original_filename, video_uuid, original_filename,
                seg['start'], seg['end'], current_tl_frame,
                category=seg['category'], title=seg['title'], reason=seg['reason'],
                link_data=link_cut
            ))
            
            # A3 Item
            a3_items.append(self._create_rough_clip_item(
                id_a3, "audio", meta, original_filename, video_uuid, original_filename,
                seg['start'], seg['end'], current_tl_frame,
                audio_channel_index=1, 
                link_data=link_cut
            ))
            
            # A4 Item
            a4_items.append(self._create_rough_clip_item(
                id_a4, "audio", meta, original_filename, video_uuid, original_filename,
                seg['start'], seg['end'], current_tl_frame,
                audio_channel_index=1, 
                link_data=link_cut
            ))
            
            in_f = self._sec_to_frame(seg['start'], meta['fps'])
            out_f = self._sec_to_frame(seg['end'], meta['fps'])
            current_tl_frame += (out_f - in_f)

        # XML Assembly (Timeline 1.xml Style)
        full_duration_frame = meta['total_frames']
        timeline_duration = max(full_duration_frame, current_tl_frame)
        
        # [수정] Version 5 & Timecode block 추가
        header = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE xmeml>',
            '<xmeml version="5">',
            '  <sequence>',
            '    <name>AI_Smart_Rough_Cut_Resolve</name>',
            f'    <duration>{timeline_duration}</duration>',
            '    <rate>',
            f'      <timebase>{meta["timebase"]}</timebase>',
            f'      <ntsc>{meta["ntsc"]}</ntsc>',
            '    </rate>',
            '    <in>-1</in>',
            '    <out>-1</out>',
            '    <timecode>',
            '      <string>01:00:00:00</string>',
            '      <frame>216000</frame>',
            '      <displayformat>NDF</displayformat>',
            '      <rate>',
            f'        <timebase>{meta["timebase"]}</timebase>',
            f'        <ntsc>{meta["ntsc"]}</ntsc>',
            '      </rate>',
            '    </timecode>',
            '    <media>'
        ]

        # Video Tracks
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
            '        <track>', # V1
            '          <enabled>TRUE</enabled>',
            '          <locked>FALSE</locked>',
            *v1_items,
            '        </track>',
            '        <track>', # V2
            '          <enabled>TRUE</enabled>',
            '          <locked>FALSE</locked>',
            *v2_items,
            '        </track>',
            '      </video>'
        ]

        # Audio Tracks
        audio_block = [
            '      <audio>',
            '        <track>', # A1
            '          <enabled>TRUE</enabled>',
            '          <locked>FALSE</locked>',
            *a1_items,
            '        </track>',
            '        <track>', # A2
            '          <enabled>TRUE</enabled>',
            '          <locked>FALSE</locked>',
            *a2_items,
            '        </track>',
            '        <track>', # A3
            '          <enabled>TRUE</enabled>',
            '          <locked>FALSE</locked>',
            *a3_items,
            '        </track>',
            '        <track>', # A4
            '          <enabled>TRUE</enabled>',
            '          <locked>FALSE</locked>',
            *a4_items,
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
            
        print(f"--- [Exporter] Rough Cut XML Generated (Resolve Style): {output_path} ---")
        return output_path