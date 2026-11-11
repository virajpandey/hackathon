#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// ---- Wi-Fi settings ----
#define USE_AP_MODE false   // true = the ESP32 creates its own Wi-Fi network
const char* ssid     = "UnknownMissileInBound";
const char* password = "Nwordsinparis";

httpd_handle_t server = NULL;

esp_err_t stream_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=frame");
  char part[96];
  while (true) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Frame capture failed");
      return ESP_FAIL;
    }
    size_t hlen = snprintf(part, sizeof(part),
      "\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", fb->len);
    esp_err_t res = httpd_resp_send_chunk(req, part, hlen);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    if (res != ESP_OK) break;   // browser closed the page
  }
  return ESP_OK;
}

void startServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  httpd_uri_t uri = {};
  uri.uri = "/";
  uri.method = HTTP_GET;
  uri.handler = stream_handler;
  if (httpd_start(&server, &config) == ESP_OK) {
    httpd_register_uri_handler(server, &uri);
  }
}

bool startCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer   = LEDC_TIMER_0;
  c.pin_d0 = 15;  c.pin_d1 = 17;  c.pin_d2 = 18;  c.pin_d3 = 16;
  c.pin_d4 = 14;  c.pin_d5 = 12;  c.pin_d6 = 11;  c.pin_d7 = 48;
  c.pin_xclk  = 10;
  c.pin_pclk  = 13;
  c.pin_vsync = 38;
  c.pin_href  = 47;
  c.pin_sccb_sda = 40;
  c.pin_sccb_scl = 39;
  c.pin_pwdn  = -1;
  c.pin_reset = -1;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size   = FRAMESIZE_VGA;     // 640x480
  c.jpeg_quality = 12;                // lower = better quality, bigger frames
  c.fb_count     = 2;
  c.fb_location  = CAMERA_FB_IN_PSRAM;
  c.grab_mode    = CAMERA_GRAB_LATEST;

  if (!psramFound()) {
    Serial.println("No PSRAM - check Tools > PSRAM setting");
    c.frame_size  = FRAMESIZE_QVGA;
    c.fb_count    = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  if (!startCamera()) return;
  Serial.println("Camera ready");

  if (USE_AP_MODE) {
    WiFi.softAP("XIAO-Cam", "12345678");
    Serial.println("Connect to Wi-Fi 'XIAO-Cam' (password 12345678)");
    Serial.print("Then open: http://");
    Serial.println(WiFi.softAPIP());
  } else {
    WiFi.begin(ssid, password);
    WiFi.setSleep(false);
    Serial.print("Connecting to Wi-Fi");
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }
    Serial.println();
    Serial.print("Open in your browser: http://");
    Serial.println(WiFi.localIP());
  }

  startServer();
}

void loop() {
  delay(10000);
}