// static/admin.js
// Подтверждение перед перезапуском API-сервера

const restartForm = document.querySelector('#server-control form');
if (restartForm) {
  restartForm.addEventListener('submit', function(event) {
    const ok = confirm('Вы уверены, что хотите перезапустить API-сервер с новыми настройками?');
    if (!ok) {
      event.preventDefault();
    }
  });
}
