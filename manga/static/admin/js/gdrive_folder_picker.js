(function () {
  "use strict";

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function showPickerErr(msg) {
    var el = qs("#manga-gdrive-picker-err");
    if (el) {
      el.textContent = msg || "";
      el.style.display = msg ? "block" : "none";
    } else {
      window.alert(msg || "Picker error");
    }
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.onload = function () {
        resolve();
      };
      s.onerror = function () {
        reject(new Error("Failed to load " + src));
      };
      document.head.appendChild(s);
    });
  }

  function fetchPickerPayload() {
    var url = window.MANGA_GDRIVE_PICKER_TOKEN_URL;
    if (!url) {
      return Promise.reject(new Error("Missing picker token URL."));
    }
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) {
          throw new Error(body.error || r.statusText || "Token request failed");
        }
        return body;
      });
    });
  }

  function openPicker(oauthToken, apiKey) {
    var g = window.google;
    if (!g || !g.picker) {
      throw new Error("Google Picker API not loaded.");
    }
    new g.picker.PickerBuilder()
      .addView(
        new g.picker.DocsView(g.picker.ViewId.FOLDERS)
          .setIncludeFolders(true)
          .setSelectFolderEnabled(true),
      )
      .setOAuthToken(oauthToken)
      .setDeveloperKey(apiKey)
      .setCallback(pickerCallback)
      .setTitle("Select parent folder for Manga library root")
      .build()
      .setVisible(true);
  }

  function pickerCallback(data) {
    var g = window.google;
    var action = data[g.picker.Response.ACTION];
    if (action === g.picker.Action.PICKED) {
      var docs = data[g.picker.Response.DOCUMENTS];
      if (docs && docs.length) {
        var id = docs[0][g.picker.Document.ID];
        var input = qs("#id_parent_folder_id");
        if (input) {
          input.value = id;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }
        showPickerErr("");
      }
    } else if (action === g.picker.Action.CANCEL) {
      showPickerErr("");
    }
  }

  function onPickClick(ev) {
    ev.preventDefault();
    showPickerErr("");
    var btn = ev.currentTarget;
    if (btn.disabled) {
      return;
    }
    btn.disabled = true;
    var chain = Promise.resolve();
    if (!(window.gapi && window.gapi.load)) {
      chain = chain.then(function () {
        return loadScript("https://apis.google.com/js/api.js");
      });
    }
    chain = chain
      .then(function () {
        return new Promise(function (resolve, reject) {
          window.gapi.load("picker", {
            callback: resolve,
            onerror: function () {
              reject(new Error("gapi.load picker failed"));
            },
          });
        });
      })
      .then(function () {
        return fetchPickerPayload();
      })
      .then(function (payload) {
        openPicker(payload.access_token, payload.api_key);
      })
      .catch(function (err) {
        showPickerErr(err && err.message ? err.message : String(err));
      })
      .then(function () {
        btn.disabled = false;
      });
  }

  function init() {
    var btn = qs("#manga-gdrive-folder-picker-btn");
    if (!btn) {
      return;
    }
    btn.addEventListener("click", onPickClick);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
