import logging
import os
import time
import re
import requests
import threading
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class Publisher:
    def __init__(self, session_manager, file_manager, db):
        self.session_manager = session_manager
        self.fm = file_manager
        self.db = db
        self.active_publishes = {}
        self.publish_threads = {}
        self.FOLDER_TIMEOUT = 60
        self.STOP_FLAG = {}
        self.PAUSE_FLAG = {}

    def extract_chat_id(self, folder_name):
        """Извлекает chat_id из названия папки"""
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            chat_id = match.group(1)
            if len(chat_id) >= 10:
                return chat_id
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return match.group(1)
        return None

    def _upload_file_to_max(self, image_data, user_id):
        """Загружает ОДНО изображение через POST /uploads"""
        try:
            if self.STOP_FLAG.get(user_id, False):
                return None

            response = requests.post(
                f"{self.session_manager.base_url}/uploads",
                headers={"Authorization": self.session_manager.token},
                params={"type": "image"},
                timeout=30,
                verify=False
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения URL: {response.status_code}")
                return None
            
            upload_data = response.json()
            upload_url = upload_data.get('url')
            
            if not upload_url:
                logger.error(f"❌ Не получен URL: {upload_data}")
                return None
            
            # Извлекаем байты
            if isinstance(image_data, dict):
                if 'data' in image_data:
                    img_data = image_data['data']
                else:
                    for key, value in image_data.items():
                        if isinstance(value, (list, bytes, bytearray)):
                            img_data = value
                            break
                    else:
                        logger.error(f"❌ В словаре нет данных: {image_data.keys()}")
                        return None
            else:
                img_data = image_data
            
            if isinstance(img_data, list):
                image_bytes = bytes(img_data)
            elif isinstance(img_data, (bytes, bytearray)):
                image_bytes = bytes(img_data)
            else:
                logger.error(f"❌ Неподдерживаемый тип данных: {type(img_data)}")
                return None
            
            files = {'data': ('image.jpg', image_bytes, 'image/jpeg')}
            
            upload_response = requests.post(
                upload_url,
                files=files,
                timeout=60,
                verify=False
            )
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Ошибка загрузки: {upload_response.status_code}")
                return None
            
            upload_result = upload_response.json()
            
            token = None
            if 'photos' in upload_result and isinstance(upload_result['photos'], dict):
                for photo_data in upload_result['photos'].values():
                    if isinstance(photo_data, dict) and 'token' in photo_data:
                        token = photo_data['token']
                        break
            
            if not token and 'token' in upload_result:
                token = upload_result['token']
            
            if not token:
                logger.error(f"❌ Не получен токен: {upload_result}")
                return None
            
            logger.info(f"✅ Файл загружен, токен: {token[:20]}...")
            time.sleep(1)
            return token
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
            return None

    def _send_to_chat(self, user_id, chat_id, text, image_tokens):
        """Отправляет сообщение через сессию пользователя"""
        try:
            attachments = []
            for token in image_tokens[:10]:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            
            success, message_id = self.session_manager.send_message(
                user_id=user_id,
                chat_id=chat_id_with_dash,
                text=text,
                attachments=attachments
            )
            
            if success and message_id:
                full_url = f"https://max.ru/c/{chat_id_with_dash}/{message_id}"
                logger.info(f"🔗 Ссылка на сообщение: {full_url}")
                return True, full_url
            
            return False, None
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False, None

    def _parse_metadata(self, metadata_text):
        """Парсит метаданные из текста после #изъятая"""
        metadata = {}
        if not metadata_text:
            return metadata
        
        fields = {
            'Название': r'Название:\s*(.+)',
            'Ссылка': r'Ссылка:\s*(.+)',
            'Код предложения': r'Код предложения:\s*(.+)',
            'Цена в лизинге': r'Цена\s*[вВ]\s*лизинге:\s*(.+)',
        }
        
        for key, pattern in fields.items():
            match = re.search(pattern, metadata_text, re.IGNORECASE)
            if match:
                metadata[key] = match.group(1).strip()
        
        return metadata

    def publish_multi(self, user_id, folders_data, settings):
        """Публикует объявления из нескольких папок с настройками"""
        try:
            # Собираем все объявления
            all_ads = []
            for folder in folders_data:
                folder_name = folder.get('folderName')
                ads = folder.get('ads', [])
                
                for ad in ads:
                    all_ads.append({
                        'folder_name': folder_name,
                        'sub_folder': ad.get('subFolder', ''),
                        'ad_text': ad.get('adText', ''),
                        'metadata_text': ad.get('metadataText', ''),
                        'images': ad.get('images', [])
                    })
            
            logger.info(f"📊 Всего объявлений: {len(all_ads)}")
            
            # Порядок публикации
            order = settings.get('order', 'sequential')
            if order == 'shuffle':
                import random
                random.shuffle(all_ads)
                logger.info("🔄 Перемешаны случайно")
            elif order == 'round_robin':
                grouped = {}
                for ad in all_ads:
                    key = ad['folder_name']
                    if key not in grouped:
                        grouped[key] = []
                    grouped[key].append(ad)
                
                all_ads = []
                max_len = max(len(v) for v in grouped.values())
                for i in range(max_len):
                    for folder_name, ads in grouped.items():
                        if i < len(ads):
                            all_ads.append(ads[i])
                logger.info(f"🔄 Круговой порядок: {len(all_ads)}")
            
            delay = settings.get('delay', 180)
            max_photos = settings.get('maxPhotos', 3)
            on_error = settings.get('onError', 'continue')
            
            success_count = 0
            error_count = 0
            errors = []
            
            for i, ad in enumerate(all_ads):
                if self.STOP_FLAG.get(user_id, False):
                    logger.info(f"⏹️ Остановка на {i+1}")
                    break
                
                progress = ((i + 1) / len(all_ads)) * 100
                logger.info(f"📤 {i+1}/{len(all_ads)} ({progress:.1f}%)")
                
                images = ad['images'][:max_photos]
                
                success = False
                attempts = 0
                max_attempts = 3 if on_error == 'retry' else 1
                
                while not success and attempts < max_attempts:
                    attempts += 1
                    try:
                        folder_name = ad['sub_folder'] or ad['folder_name']
                        chat_id = self.extract_chat_id(folder_name)
                        
                        if not chat_id:
                            raise ValueError(f"Не удалось извлечь chat_id из {folder_name}")
                        
                        # Загружаем изображения
                        image_tokens = []
                        for img_data in images:
                            token = self._upload_file_to_max(img_data, user_id)
                            if token:
                                image_tokens.append(token)
                        
                        # Отправляем
                        success, full_url = self._send_to_chat(
                            user_id, chat_id, ad['ad_text'], image_tokens
                        )
                        
                        if success:
                            metadata = self._parse_metadata(ad.get('metadata_text', ''))
                            self.db.save_ad_metadata(
                                user_id, folder_name, f"-{chat_id}", metadata, time.time()
                            )
                            self.db.add_publication(
                                user_id, folder_name, f"-{chat_id}", 
                                full_url.split('/')[-1] if full_url else None,
                                full_url
                            )
                            success_count += 1
                            logger.info(f"✅ {folder_name} - успешно")
                        else:
                            raise Exception("Не удалось отправить сообщение")
                        
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"❌ Ошибка {ad.get('sub_folder')}: {error_msg}")
                        
                        if attempts >= max_attempts:
                            error_count += 1
                            errors.append({
                                'folder': ad.get('sub_folder'),
                                'error': error_msg
                            })
                            chat_id = self.extract_chat_id(ad.get('sub_folder', '')) or 'unknown'
                            self.db.add_publication_error(
                                user_id, ad.get('sub_folder'), chat_id, error_msg
                            )
                            
                            if on_error == 'stop':
                                return {
                                    'success': False,
                                    'success_count': success_count,
                                    'error_count': error_count,
                                    'message': f'Остановлено: {error_msg}'
                                }
                        else:
                            logger.info(f"🔄 Повтор {attempts}/{max_attempts}")
                            time.sleep(5)
                
                # Задержка
                if i < len(all_ads) - 1 and success:
                    logger.info(f"⏳ Задержка {delay}с")
                    for _ in range(delay):
                        if self.STOP_FLAG.get(user_id, False):
                            break
                        time.sleep(1)
            
            return {
                'success': True,
                'success_count': success_count,
                'error_count': error_count,
                'total': len(all_ads),
                'errors': errors,
                'message': f'Успешно: {success_count}, Ошибок: {error_count}'
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}

    def stop(self, user_id):
        """Останавливает публикацию"""
        self.STOP_FLAG[user_id] = True
        try:
            user_folder = self.fm.get_user_folder(user_id)
            if os.path.exists(user_folder):
                import shutil
                shutil.rmtree(user_folder)
                os.makedirs(user_folder, exist_ok=True)
        except Exception as e:
            logger.error(f"❌ Ошибка удаления: {e}")
        
        def reset():
            time.sleep(5)
            self.STOP_FLAG[user_id] = False
        threading.Thread(target=reset, daemon=True).start()
        return True
