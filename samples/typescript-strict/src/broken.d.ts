// PROVES: "skipLibCheck": true — BY STAYING SILENT.
//
// This declaration file references a type that does not exist. skipLibCheck
// skips type checking inside .d.ts files, so it is silent today. Remove the
// flag and it becomes TS2304, a NEW finding the manifest does not expect, and
// CI goes red.
//
// The point is not that the broken declaration is good; it is that skipLibCheck
// is a real relaxation with a real cost, and the baseline should not be able to
// drop it without anyone noticing.
//
// MUST PRODUCE: nothing.
declare module 'not-a-real-package' {
  export const value: ThisTypeDoesNotExist;
}
