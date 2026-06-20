const modal = document.querySelector(".video-modal");
const modalVideo = modal.querySelector("video");
const modalTitle = modal.querySelector("#video-modal-title");
const closeButton = modal.querySelector(".modal-close");
const videoTriggers = document.querySelectorAll(".video-trigger");
let activeTrigger = null;

function closeVideo() {
  modalVideo.pause();
  modalVideo.removeAttribute("src");
  modalVideo.load();
  modal.close();
  document.body.classList.remove("modal-open");

  if (activeTrigger) {
    activeTrigger.focus();
    activeTrigger = null;
  }
}

videoTriggers.forEach((trigger) => {
  trigger.addEventListener("click", () => {
    activeTrigger = trigger;
    modalTitle.textContent = trigger.dataset.title;
    modalVideo.src = trigger.dataset.video;
    modal.showModal();
    document.body.classList.add("modal-open");
    modalVideo.play().catch(() => {
      // Native controls remain available when browser autoplay policy blocks playback.
    });
  });
});

closeButton.addEventListener("click", closeVideo);

modal.addEventListener("click", (event) => {
  if (event.target === modal) {
    closeVideo();
  }
});

modal.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeVideo();
});

document.querySelector("#current-year").textContent = new Date().getFullYear();
