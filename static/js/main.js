document.addEventListener("DOMContentLoaded", function () {
  // --- gallery ---
  var mainImg = document.getElementById("gallery-main-img");
  var thumbs = document.querySelectorAll(".gallery-thumbs [data-src]");
  thumbs.forEach(function (t) {
    t.addEventListener("click", function () {
      var src = t.getAttribute("data-src");
      if (src && mainImg) {
        mainImg.src = src;
        document.querySelectorAll(".gallery-thumbs img").forEach(function (i) {
          i.classList.remove("active");
        });
        if (t.tagName === "IMG") t.classList.add("active");
      }
    });
  });

  if (mainImg) {
    mainImg.addEventListener("click", function () {
      if (mainImg.style.objectFit === "contain" && mainImg.classList.contains("zoomed")) {
        mainImg.classList.remove("zoomed");
        mainImg.style.transform = "scale(1)";
        mainImg.style.cursor = "zoom-in";
      } else {
        mainImg.classList.add("zoomed");
        mainImg.style.transform = "scale(1.9)";
        mainImg.style.cursor = "zoom-out";
      }
    });
  }

  // --- info tabs ---
  var tabButtons = document.querySelectorAll(".info-tabs button");
  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = btn.getAttribute("data-tab");
      tabButtons.forEach(function (b) { b.classList.remove("active"); });
      document.querySelectorAll(".info-panel").forEach(function (p) { p.classList.remove("active"); });
      btn.classList.add("active");
      var panel = document.getElementById(target);
      if (panel) panel.classList.add("active");
    });
  });

  // --- add to cart via fetch ---
  var addForms = document.querySelectorAll(".add-to-cart-form");
  addForms.forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var fd = new FormData(form);
      fetch(form.action, {
        method: "POST",
        body: fd,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            document.querySelectorAll(".cart-count").forEach(function (el) {
              el.textContent = data.cart_count;
            });
            showToast();
          }
        })
        .catch(function () {
          form.submit();
        });
    });
  });

  function showToast() {
    var existing = document.querySelector(".toast");
    if (existing) existing.remove();
    var toast = document.createElement("div");
    toast.className = "toast";
    toast.innerHTML = 'Товар добавлен в корзину. Чтобы купить, перейдите в <a href="/cart">корзину</a>';
    document.body.appendChild(toast);
    setTimeout(function () {
      toast.remove();
    }, 4500);
  }
});
