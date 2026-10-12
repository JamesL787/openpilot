import { api } from "../api.js"

// D-116: answer the car's faster-route offer (D-111) from the Galaxy. Polls only while the Navigation page is open.
export const RerouteOfferBanner = {
  name: "RerouteOfferBanner",
  data() { return { offer: null, busy: false, timer: null } },
  computed: {
    minutes() { return Math.max(Math.round((this.offer?.savings_s || 0) / 60), 1) },
  },
  mounted() {
    this.poll()
    this.timer = setInterval(() => this.poll(), 2000)
  },
  beforeUnmount() { clearInterval(this.timer) },
  methods: {
    async poll() {
      if (this.busy) return
      try {
        const data = await api.getRerouteOffer()
        this.offer = data?.offer || null
      } catch {
        this.offer = null
      }
    },
    async answer(accept) {
      if (!this.offer || this.busy) return
      this.busy = true
      try {
        await api.answerRerouteOffer(this.offer.id, accept)
        this.offer = null
      } catch {
        // the offer expired or was answered on the car; the next poll clears it
      } finally {
        this.busy = false
      }
    },
  },
  template: `
    <div v-if="offer" class="gx-alert gx-alert--info" role="status" style="align-items:center; gap:12px;">
      <i class="bi bi-signpost-split gx-alert__icon"></i>
      <div class="gx-alert__body" style="flex:1;">
        <strong>Faster route: {{ minutes }} min faster</strong>
        <span>The car is asking. Nothing changes unless you tap Switch.</span>
      </div>
      <button type="button" class="gx-btn" :disabled="busy" @click="answer(true)">Switch</button>
      <button type="button" class="gx-btn" :disabled="busy" @click="answer(false)">Keep</button>
    </div>
  `,
}
