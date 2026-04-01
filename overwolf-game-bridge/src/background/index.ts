import { AppController } from "./app-controller";
import { OverwolfRuntime } from "./gep/runtime";

const controller = new AppController();
const runtime = new OverwolfRuntime(controller);

void runtime.start();

console.log("Overwolf Game Bridge background controller initialized.");
