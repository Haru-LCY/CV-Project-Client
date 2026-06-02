let bridge = null;
let previewIsCurrent = false;
let activeEmotion = "happy";
let emotionImageSources = {};
let historyCards = [];

const els = {};
const EMOTIONS = ["happy", "angry", "shy", "sad"];

document.addEventListener("DOMContentLoaded", () => {
  for (const id of [
    "userName",
    "historySelect",
    "loadHistoryButton",
    "styleSelect",
    "appearanceTraits",
    "personalityTraits",
    "identityTraits",
    "imagePlaceholder",
    "previewImage",
    "emotionTabs",
    "characterName",
    "characterGreeting",
    "characterPersona",
    "statusText",
    "generateButton",
    "saveCardButton",
    "applyButton",
    "cancelButton",
  ]) {
    els[id] = document.getElementById(id);
  }

  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.characterWorkbench;
    connectBridgeSignals();
    bridge.getInitialState((rawState) => {
      renderInitialState(JSON.parse(rawState));
    });
  });
});

function connectBridgeSignals() {
  bridge.generationStarted.connect(() => {
    setBusy(true);
    previewIsCurrent = false;
    els.applyButton.disabled = true;
    els.saveCardButton.disabled = true;
    els.statusText.textContent = "正在生成人设和四张情感预览图...";
    showPlaceholder("生成中...");
    resetEmotionPreview();
    els.characterName.textContent = "-";
    els.characterGreeting.textContent = "-";
    els.characterPersona.value = "";
  });

  bridge.generationFinished.connect((rawProfile) => {
    setBusy(false);
    const profile = JSON.parse(rawProfile);
    previewIsCurrent = true;
    els.applyButton.disabled = false;
    els.saveCardButton.disabled = false;
    els.statusText.textContent = "预览已生成，满意后点击“应用角色”。";
    els.characterName.textContent = profile.name || "-";
    els.characterGreeting.textContent = profile.greeting || "-";
    els.characterPersona.value = profile.persona || "";
    emotionImageSources = normalizeEmotionImages(profile);
    renderEmotionAvailability();
    if (!showEmotion(activeEmotion)) {
      showPlaceholder("没有可用预览图");
    }
  });

  bridge.generationFailed.connect((message) => {
    setBusy(false);
    previewIsCurrent = false;
    els.applyButton.disabled = true;
    els.saveCardButton.disabled = true;
    els.statusText.textContent = `生成失败：${message || "unknown error"}`;
    if (!els.previewImage.src) {
      showPlaceholder("生成失败");
    }
  });

  bridge.previewStale.connect(() => {
    previewIsCurrent = false;
    els.applyButton.disabled = true;
    els.saveCardButton.disabled = true;
    els.statusText.textContent = "选择已修改，请重新生成预览。";
  });

  bridge.cardSaved.connect((path) => {
    els.statusText.textContent = `角色卡已保存：${path}`;
    bridge.getHistoryCards((rawCards) => {
      renderHistoryCards(JSON.parse(rawCards));
    });
  });

  bridge.cardSaveFailed.connect((message) => {
    els.statusText.textContent = `保存失败：${message || "unknown error"}`;
  });
}

function renderInitialState(state) {
  const options = state.options || {};
  const defaults = state.defaults || {};

  els.userName.value = state.userName || "用户";
  renderHistoryCards(state.historyCards || []);
  renderStyleSelect(options.styles || [], defaults.style);
  renderAppearanceGroups(
    els.appearanceTraits,
    options.appearance_groups || null,
    options.appearance_traits || [],
    defaults.appearance_traits || [],
  );
  renderChips(els.personalityTraits, options.personality_traits || [], defaults.personality_traits || []);
  renderChips(els.identityTraits, options.identity_traits || [], defaults.identity_traits || []);

  els.userName.addEventListener("input", markStale);
  els.styleSelect.addEventListener("change", markStale);
  document.querySelectorAll(".chip input").forEach((input) => {
    input.addEventListener("change", markStale);
  });

  els.generateButton.addEventListener("click", startGeneration);
  els.loadHistoryButton.addEventListener("click", loadSelectedHistory);
  els.saveCardButton.addEventListener("click", () => bridge.saveCharacterCard());
  els.applyButton.addEventListener("click", () => bridge.applyCharacter());
  els.cancelButton.addEventListener("click", () => bridge.cancel());
  els.emotionTabs.querySelectorAll(".emotion-tab").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveEmotion(button.dataset.emotion);
    });
  });
}

function renderHistoryCards(cards) {
  historyCards = Array.isArray(cards) ? cards : [];
  els.historySelect.innerHTML = "";
  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = historyCards.length ? "选择已保存角色" : "暂无历史角色";
  els.historySelect.appendChild(emptyOption);

  for (const card of historyCards) {
    const option = document.createElement("option");
    option.value = card.path;
    option.textContent = card.name ? `${card.name} · ${card.filename}` : card.filename;
    els.historySelect.appendChild(option);
  }
  els.loadHistoryButton.disabled = true;
  els.historySelect.disabled = !historyCards.length;
  els.historySelect.onchange = () => {
    els.loadHistoryButton.disabled = !els.historySelect.value;
  };
}

function loadSelectedHistory() {
  const path = els.historySelect.value;
  if (!path) {
    return;
  }
  bridge.loadHistoryCard(path);
}

function renderStyleSelect(styles, defaultStyle) {
  els.styleSelect.innerHTML = "";
  for (const style of styles) {
    const option = document.createElement("option");
    option.value = style;
    option.textContent = style;
    option.selected = style === defaultStyle;
    els.styleSelect.appendChild(option);
  }
}

function renderAppearanceGroups(container, groups, fallbackValues, defaults) {
  container.innerHTML = "";
  const selected = new Set(defaults);
  const normalizedGroups = normalizeAppearanceGroups(groups, fallbackValues);
  let groupIndex = 0;
  for (const [groupName, values] of normalizedGroups) {
    const details = document.createElement("details");
    details.className = "appearance-folder";
    details.open = groupIndex < 2 || values.some((value) => selected.has(value));

    const summary = document.createElement("summary");
    const title = document.createElement("span");
    title.textContent = groupName;
    const count = document.createElement("em");
    count.textContent = `${values.length} 项`;
    summary.append(title, count);
    details.appendChild(summary);

    const list = document.createElement("div");
    list.className = "chip-list nested";
    renderChipItems(list, values, selected);
    details.appendChild(list);
    container.appendChild(details);
    groupIndex += 1;
  }
}

function normalizeAppearanceGroups(groups, fallbackValues) {
  if (groups && !Array.isArray(groups) && typeof groups === "object") {
    return Object.entries(groups).filter(([, values]) => Array.isArray(values));
  }
  if (Array.isArray(groups)) {
    return groups
      .map((group) => [group.name || group.title || "外貌", group.values || group.traits || []])
      .filter(([, values]) => Array.isArray(values));
  }
  return [["外貌", fallbackValues || []]];
}

function renderChips(container, values, defaults) {
  container.innerHTML = "";
  const selected = new Set(defaults);
  renderChipItems(container, values, selected);
}

function renderChipItems(container, values, selected) {
  for (const value of values) {
    const label = document.createElement("label");
    label.className = "chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = value;
    input.checked = selected.has(value);
    const span = document.createElement("span");
    span.textContent = value;
    label.append(input, span);
    container.appendChild(label);
  }
}

function selectedValues(container) {
  return Array.from(container.querySelectorAll("input:checked")).map((input) => input.value);
}

function startGeneration() {
  const payload = {
    user_name: els.userName.value.trim() || "用户",
    appearance_traits: selectedValues(els.appearanceTraits),
    personality_traits: selectedValues(els.personalityTraits),
    identity_traits: selectedValues(els.identityTraits),
    style: els.styleSelect.value,
  };
  bridge.startGeneration(JSON.stringify(payload));
}

function markStale() {
  if (!previewIsCurrent) {
    return;
  }
  bridge.markStale();
}

function normalizeEmotionImages(profile) {
  const images = {};
  const emotionImages = profile.emotion_images || {};
  for (const emotion of EMOTIONS) {
    const image = emotionImages[emotion];
    if (typeof image === "string") {
      images[emotion] = image;
    } else if (image && image.image_src) {
      images[emotion] = image.image_src;
    }
  }
  if (profile.image_src && !Object.keys(images).length) {
    images.happy = profile.image_src;
  }
  return images;
}

function setActiveEmotion(emotion) {
  if (!EMOTIONS.includes(emotion)) {
    return;
  }
  activeEmotion = emotion;
  renderEmotionAvailability();
  if (!showEmotion(emotion)) {
    showPlaceholder("这个情感还没有预览图");
  }
}

function showEmotion(emotion) {
  const src = emotionImageSources[emotion];
  if (!src) {
    return false;
  }
  els.previewImage.src = src;
  els.previewImage.hidden = false;
  els.imagePlaceholder.hidden = true;
  els.imagePlaceholder.textContent = "";
  return true;
}

function renderEmotionAvailability() {
  els.emotionTabs.querySelectorAll(".emotion-tab").forEach((button) => {
    const emotion = button.dataset.emotion;
    button.classList.toggle("is-active", emotion === activeEmotion);
    button.classList.toggle("is-missing", !emotionImageSources[emotion]);
  });
}

function resetEmotionPreview() {
  activeEmotion = "happy";
  emotionImageSources = {};
  renderEmotionAvailability();
}

function setBusy(isBusy) {
  els.generateButton.disabled = isBusy;
  els.saveCardButton.disabled = isBusy || !previewIsCurrent;
  els.cancelButton.disabled = isBusy;
  els.userName.disabled = isBusy;
  els.styleSelect.disabled = isBusy;
  document.querySelectorAll(".chip input").forEach((input) => {
    input.disabled = isBusy;
  });
}

function showPlaceholder(text) {
  els.previewImage.hidden = true;
  els.previewImage.removeAttribute("src");
  els.imagePlaceholder.hidden = false;
  els.imagePlaceholder.textContent = text;
}
