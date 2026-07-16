# В классе DebugAPIClient добавьте этот метод вместо существующего
def upload_file(self, image_data) -> Optional[str]:
    """Загружает файл с логированием"""
    if not self.token:
        logger.error("❌ [UPLOAD] Токен не установлен")
        return None
    
    try:
        # 1. Получаем URL для загрузки
        url = f"{self.base_url}/uploads"
        headers = {"Authorization": self.token}
        params = {"type": "image"}
        
        logger.info(f"📤 [UPLOAD] Запрос URL для загрузки")
        logger.info(f"  URL: {url}")
        logger.info(f"  Headers: Authorization={self.token[:15]}...")
        logger.info(f"  Params: {params}")
        
        response = requests.post(
            url,
            headers=headers,
            params=params,
            timeout=30,
            verify=False
        )
        
        logger.info(f"  Response status: {response.status_code}")
        logger.info(f"  Response headers: {dict(response.headers)}")
        
        self._log_request("POST", url, headers, {"params": params}, response)
        
        if response.status_code != 200:
            logger.error(f"❌ [UPLOAD] Ошибка получения URL: {response.status_code}")
            logger.error(f"  Response body: {response.text[:500]}")
            return None
        
        try:
            upload_data = response.json()
            logger.info(f"  Response JSON: {json.dumps(upload_data, indent=2)[:500]}")
        except Exception as e:
            logger.error(f"❌ [UPLOAD] Не удалось распарсить JSON: {e}")
            logger.error(f"  Response text: {response.text[:500]}")
            return None
        
        upload_url = upload_data.get('url')
        if not upload_url:
            logger.error(f"❌ [UPLOAD] Не получен URL: {upload_data}")
            return None
        
        logger.info(f"✅ [UPLOAD] Получен URL для загрузки: {upload_url[:100]}...")
        
        # 2. Извлекаем байты изображения
        if isinstance(image_data, dict):
            if 'data' in image_data:
                img_data = image_data['data']
            else:
                for key, value in image_data.items():
                    if isinstance(value, (list, bytes, bytearray)):
                        img_data = value
                        break
                else:
                    logger.error(f"❌ [UPLOAD] В словаре нет данных: {image_data.keys()}")
                    return None
        else:
            img_data = image_data
        
        if isinstance(img_data, list):
            image_bytes = bytes(img_data)
        elif isinstance(img_data, (bytes, bytearray)):
            image_bytes = bytes(img_data)
        else:
            logger.error(f"❌ [UPLOAD] Неподдерживаемый тип данных: {type(img_data)}")
            return None
        
        logger.info(f"📸 [UPLOAD] Размер изображения: {len(image_bytes)} байт")
        
        # 3. Отправляем файл
        files = {'data': ('image.jpg', image_bytes, 'image/jpeg')}
        
        logger.info(f"📤 [UPLOAD] Отправка файла на {upload_url[:100]}...")
        
        upload_response = requests.post(
            upload_url,
            files=files,
            timeout=60,
            verify=False
        )
        
        logger.info(f"  Upload status: {upload_response.status_code}")
        logger.info(f"  Upload headers: {dict(upload_response.headers)}")
        
        self._log_request("POST", upload_url, {}, {"files": "binary data"}, upload_response)
        
        if upload_response.status_code != 200:
            logger.error(f"❌ [UPLOAD] Ошибка загрузки: {upload_response.status_code}")
            logger.error(f"  Response body: {upload_response.text[:500]}")
            return None
        
        try:
            upload_result = upload_response.json()
            logger.info(f"  Upload result: {json.dumps(upload_result, indent=2)[:500]}")
        except Exception as e:
            logger.error(f"❌ [UPLOAD] Не удалось распарсить JSON ответа: {e}")
            logger.error(f"  Response text: {upload_response.text[:500]}")
            return None
        
        # 4. Извлекаем токен
        token = None
        if 'photos' in upload_result and isinstance(upload_result['photos'], dict):
            for photo_key, photo_data in upload_result['photos'].items():
                if isinstance(photo_data, dict) and 'token' in photo_data:
                    token = photo_data['token']
                    logger.info(f"  Найден токен в photos[{photo_key}]: {token[:20]}...")
                    break
        
        if not token and 'token' in upload_result:
            token = upload_result['token']
            logger.info(f"  Найден токен в корне: {token[:20]}...")
        
        if token:
            logger.info(f"✅ [UPLOAD] Файл загружен успешно, токен: {token[:20]}...")
            return token
        else:
            logger.error(f"❌ [UPLOAD] Не получен токен: {upload_result}")
            return None
                
    except requests.exceptions.Timeout:
        logger.error(f"❌ [UPLOAD] Таймаут при загрузке")
        return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ [UPLOAD] Ошибка соединения: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ [UPLOAD] Неизвестная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None
