// DELIBERATELY MISFORMATTED. `prettier --check` must reject this file.
//
// Nothing here is a lint or type error — the point is that the FORMATTER is the
// only thing with an opinion about it. See README.md in this directory.
//
// Ignored by .prettierignore so `prettier --write` on the repo cannot quietly
// repair the fixture.

export  const  greeting   =    "hello"

export function  add( a:number,b :number ) : number
{
      return a+b
}

export const items = [
  1,2,
      3,
  4 ]
