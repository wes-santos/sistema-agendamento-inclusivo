(function () {
  function applyTimeMask(input) {
    input.addEventListener('input', function (event) {
      var digits = input.value.replace(/\D/g, '').slice(0, 4);
      var formatted;
      if (digits.length >= 3) {
        formatted = digits.slice(0, 2) + ':' + digits.slice(2);
      } else {
        formatted = digits;
      }
      input.value = formatted;
    });

    input.addEventListener('blur', function () {
      var digits = input.value.replace(/\D/g, '');
      if (digits.length === 4) {
        input.value = digits.slice(0, 2) + ':' + digits.slice(2);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var inputs = document.querySelectorAll('input[data-mask="time-hhmm"]');
    inputs.forEach(function (input) {
      applyTimeMask(input);
    });
  });
})();
